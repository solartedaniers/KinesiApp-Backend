"""Lleno una base con datos de demostración: entrenadores, deportistas (gestionados y con cuenta), equipos y
análisis reales que pasan por la IA. Nunca invento números: cada análisis sale de un recorte de video de verdad.

Uso, desde KinesiApp-Backend (la base es la del .env con el host cambiado; el backend, el de producción):
  python -u scripts/seed_demo.py --target-host <endpoint directo> --plan <plan.json> --clips <carpeta>
      [--url <backend>]   por defecto, el backend de producción
      [--apply]           sin esto corro en seco: solo leo, en una transacción READ ONLY, y no llamo al backend

En seco compruebo el host, la migración, que las cuentas nuevas no choquen, que los nombres y las fichas
cumplan las reglas del backend y que cada recorte exista, dure 40 s o menos y tenga repeticiones; después
muestro los conteos, los recortes y cuánto tiempo de réplica de la IA va a gastar.

Con --apply:
  1. creo en la base las cuentas nuevas ya verificadas y con el consentimiento de video vigente (así no envío
     correos); todo lo demás lo hago por gRPC, como lo haría una persona;
  2. fichas, coach asignado por el admin, deportistas gestionados, equipos y miembros;
  3. cada análisis: subida firmada, PUT al bucket, confirmación y WatchAnalysis hasta PROCESSED, de a uno;
  4. reparto hacia atrás las fechas de los análisis y de los equipos creados.
Es idempotente: reconozco lo que ya existe por correo, por coach y nombre, y por el manifiesto, donde guardo el
id de cada análisis y cada equipo creado. No llamo a Gemini: los análisis de demostración quedan sin chat.
Las contraseñas las pido con getpass y nunca las imprimo.

Con --cleanup muestro lo que borraría (en seco, de solo lectura); con --cleanup --apply lo borro: los análisis por
DeleteAnalysis con la sesión del admin, para que también salgan sus videos del bucket, y después equipos,
gestionados y cuentas de demo en una sola transacción. Lo encuentro por el plan, no por el manifiesto.
"""

import argparse
import asyncio
import getpass
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import delete, func, select, text, update  # noqa: E402

from app.athletes.inputs import AthleteInputRules, ManagedAthleteInput  # noqa: E402
from app.auth.password_hasher import PasswordHasher  # noqa: E402
from app.core.async_database import build_async_engine, build_session_factory  # noqa: E402
from app.models.athlete import AthleteProfile  # noqa: E402
from app.models.jump_analysis import JumpAnalysis  # noqa: E402
from app.models.refresh_token import RefreshToken  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.settings.athlete import AthleteSettings  # noqa: E402
from app.settings.database import DatabaseSettings  # noqa: E402
from cloud_check import DEFAULT_URL, RpcClient, Session, http, upload_timeout  # noqa: E402

COLOMBIA = timezone(timedelta(hours=-5))
MAX_CLIP_SECONDS = 40
# Lo que medí en Azure (CLAUDE.md §2): la réplica analiza un poco más lento que mi PC y en frío tarda ~35 s
AZURE_SLOWDOWN = 1.25
AZURE_COLD_START_SECONDS = 35
AZURE_COOLDOWN_SECONDS = 300
PER_ANALYSIS_OVERHEAD_SECONDS = 7  # firma, PUT, confirmación, WarmUp en caliente y descarga del video
UPLOAD_MIN_KBPS = 1000
ANALYSIS = "kinesiapp.analysis.v1.AnalysisService"
ATHLETE = "kinesiapp.athlete.v1.AthleteProfileService"
MANAGED = "kinesiapp.athlete.v1.ManagedAthleteService"
TEAM = "kinesiapp.team.v1.TeamService"


class SeedAborted(Exception):
    """Algo del plan no es seguro de aplicar; no escribo nada."""


@dataclass(frozen=True)
class Person:
    full_name: str
    gender: str
    birth_date: str
    height_cm: float
    weight_kg: float
    email: str | None = None
    coach: str | None = None
    owner: str | None = None  # coach que lo gestiona, solo en los gestionados

    def biometrics(self) -> dict:
        year, month, day = (int(part) for part in self.birth_date.split("-"))
        return {"gender": f"GENDER_{self.gender.upper()}", "heightCm": self.height_cm, "weightKg": self.weight_kg,
                "birthDate": {"year": year, "month": month, "day": day}}


class Plan:
    def __init__(self, path: Path, clips_dir: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.raw = raw
        self.admin_email: str = raw["admin_email"]
        self.coaches: list[dict] = raw["coaches"]
        self.new_coaches = [coach for coach in self.coaches if not coach.get("existing")]
        self.managed = [Person(**person, owner=coach["email"]) for coach in self.coaches for person in coach["managed"]]
        self.athletes = [Person(**person) for person in raw["athletes"]]
        self.teams = [(coach["email"], team) for coach in self.coaches for team in coach["teams"]]
        self.analyses: list[dict] = raw["analyses"]
        self.clips_dir = clips_dir
        self.clips = {clip["name"]: clip for clip in json.loads((clips_dir.parent / "clips.json").read_text(encoding="utf-8"))}
        self.validation = {item["name"]: item for item in json.loads((clips_dir.parent / "validation.json").read_text(encoding="utf-8"))}
        self.people = {person.full_name: person for person in [*self.managed, *self.athletes]}

    def analysis_dates(self) -> list[datetime]:
        window = self.raw["analysis_dates"]
        first, last = date.fromisoformat(window["from"]), date.fromisoformat(window["to"])
        hours = window["hour_to"] - window["hour_from"]
        count = len(self.analyses)
        dates = []
        for index in range(count):
            day = first + timedelta(days=round(index * (last - first).days / max(count - 1, 1)))
            # Entrenan entre semana: corro el sábado al viernes y el domingo al lunes
            day += {5: timedelta(days=-1), 6: timedelta(days=1)}.get(day.weekday(), timedelta())
            moment = datetime(day.year, day.month, day.day, window["hour_from"] + index * 7 % hours, index * 13 % 60, tzinfo=COLOMBIA)
            dates.append(moment)
        return dates


class Manifest:
    """Lo que ya creé, para no repetirlo y para poder borrarlo después."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"analyses": {}, "teams": {}, "managed": {}, "accounts": {}}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")


def validate_plan(plan: Plan) -> list[str]:
    """Paso cada nombre y ficha por las mismas reglas del backend, y reviso que las referencias cuadren."""
    problems = []
    rules = AthleteInputRules.from_settings(AthleteSettings())
    for person in plan.people.values():
        try:
            rules.parse(ManagedAthleteInput, {"full_name": person.full_name, "biometrics": {
                "gender": person.gender, "height_cm": person.height_cm, "weight_kg": person.weight_kg, "birth_date": person.birth_date}})
        except ValidationError as error:
            problems.append(f"{person.full_name}: {error.errors()[0]['msg']}")
    coach_emails = {coach["email"] for coach in plan.coaches}
    for person in plan.athletes:
        if person.coach and person.coach not in coach_emails:
            problems.append(f"{person.full_name}: unknown coach {person.coach}")
    for owner, team in plan.teams:
        for member in team["members"]:
            athlete = plan.people.get(member)
            if athlete is None:
                problems.append(f"{team['name']}: unknown member {member}")
            elif (athlete.owner or athlete.coach) != owner:
                problems.append(f"{team['name']}: {member} is not coached by the team owner")
    for item in plan.analyses:
        clip = plan.clips.get(item["clip"])
        if clip is None:
            problems.append(f"clip {item['clip']} is not in clips.json")
            continue
        if item["athlete"] not in plan.people:
            problems.append(f"clip {item['clip']}: unknown athlete {item['athlete']}")
        if not (plan.clips_dir / clip["file"]).exists():
            problems.append(f"clip {item['clip']}: file is missing")
        if clip["duration_ms"] > MAX_CLIP_SECONDS * 1000:
            problems.append(f"clip {item['clip']}: lasts more than {MAX_CLIP_SECONDS} s")
        if plan.validation.get(item["clip"], {}).get("repetitions", 0) == 0:
            problems.append(f"clip {item['clip']}: the local analysis found no repetitions")
    if len({item["clip"] for item in plan.analyses}) != len(plan.analyses):
        problems.append("a clip is used twice: its video_reference would repeat the same numbers")
    return problems


async def read_state(session, plan: Plan) -> dict:
    """Todo lo que necesito saber de la base, en una transacción de solo lectura."""
    await session.execute(text("SET TRANSACTION READ ONLY"))
    emails = [plan.admin_email, *(coach["email"] for coach in plan.coaches), *(person.email for person in plan.athletes)]
    users = {user.email: user for user in await session.scalars(select(User).where(User.email.in_(emails)))}
    owners = [users[email].id for email in (coach["email"] for coach in plan.coaches) if email in users]
    managed = await session.execute(
        select(AthleteProfile.coach_id, AthleteProfile.full_name).where(AthleteProfile.user_id.is_(None), AthleteProfile.coach_id.in_(owners or [0]))
    )
    teams = await session.execute(select(Team.owner_id, Team.name).where(Team.owner_id.in_(owners or [0])))
    return {
        "database": await session.scalar(text("select current_database()")),
        "revision": await session.scalar(text("select version_num from alembic_version")),
        "users": users,
        "managed": {(coach_id, name) for coach_id, name in managed},
        "teams": {(owner_id, name) for owner_id, name in teams},
        "consent_version": await session.scalar(select(func.max(User.video_consent_version))),
        "totals": {
            "users": await session.scalar(select(func.count(User.id))),
            "athlete_profiles": await session.scalar(select(func.count(AthleteProfile.id))),
            "teams": await session.scalar(select(func.count(Team.id))),
            "analyses": await session.scalar(select(func.count(JumpAnalysis.id))),
        },
    }


def check_state(plan: Plan, state: dict) -> list[str]:
    problems = []
    users = state["users"]
    head = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()
    if state["revision"] != head:
        problems.append(f"database is at {state['revision']}, the code expects {head}")
    admin = users.get(plan.admin_email)
    if admin is None or admin.role is not UserRole.ADMIN:
        problems.append(f"{plan.admin_email} is not an ADMIN")
    for coach in plan.coaches:
        user = users.get(coach["email"])
        if coach.get("existing") and (user is None or user.role is not UserRole.COACH):
            problems.append(f"{coach['email']} must already exist as COACH")
        if not coach.get("existing") and user is not None and user.role is not UserRole.COACH:
            problems.append(f"{coach['email']} already exists with role {user.role.name}")
    for person in plan.athletes:
        user = users.get(person.email)
        if user is not None and user.role is not UserRole.ATHLETE:
            problems.append(f"{person.email} already exists with role {user.role.name}")
    return problems


def azure_estimate(plan: Plan, pending: list[dict]) -> tuple[float, float]:
    analysis = sum(plan.validation[item["clip"]]["seconds"] * AZURE_SLOWDOWN + PER_ANALYSIS_OVERHEAD_SECONDS for item in pending)
    return analysis, (AZURE_COLD_START_SECONDS + analysis + AZURE_COOLDOWN_SECONDS if pending else 0)


def print_dry_run(plan: Plan, state: dict, manifest: Manifest, host: str) -> None:
    users = state["users"]
    coach_ids = {email: users[email].id for email in (coach["email"] for coach in plan.coaches) if email in users}
    new_accounts = [coach["email"] for coach in plan.new_coaches if coach["email"] not in users] + \
        [person.email for person in plan.athletes if person.email not in users]
    new_managed = [person for person in plan.managed if (coach_ids.get(person.owner), person.full_name) not in state["managed"]]
    new_teams = [team for owner, team in plan.teams if (coach_ids.get(owner), team["name"]) not in state["teams"]]
    pending = [item for item in plan.analyses if item["clip"] not in manifest.data["analyses"]]
    dates = dict(zip((item["clip"] for item in plan.analyses), plan.analysis_dates()))

    print(f"Host: {host}\nBase: {state['database']}   migración: {state['revision']}   consentimiento vigente: v{state['consent_version']}")
    print("Hoy en la base: " + ", ".join(f"{name} {count}" for name, count in state["totals"].items()))
    print("\nVoy a crear")
    print(f"  cuentas de entrenador nuevas        {sum(1 for c in plan.new_coaches if c['email'] not in users)}")
    print(f"  cuentas de deportista nuevas        {sum(1 for p in plan.athletes if p.email not in users)}")
    print(f"  fichas de deportista con cuenta     {sum(1 for p in plan.athletes if p.email not in users)}")
    print(f"  deportistas gestionados             {len(new_managed)}")
    print(f"  equipos                             {len(new_teams)}")
    print(f"  miembros de equipo                  {sum(len(team['members']) for team in new_teams)}")
    print(f"  asignaciones de coach (admin)       {sum(1 for p in plan.athletes if p.coach and p.email not in users)}")
    print(f"  análisis (pasan por la IA)          {len(pending)}")
    print("  mensajes de chat                    0 (sin Gemini)")
    print("\nCuentas nuevas (contraseña de demo común, la pides tú con getpass):")
    for email in new_accounts:
        print(f"  {email}")
    print("\nPor entrenador")
    for coach in plan.coaches:
        accounts = [p.full_name for p in plan.athletes if p.coach == coach["email"]]
        print(f"  {coach.get('full_name', coach['email'])}: gestionados {len(coach['managed'])}, con cuenta {len(accounts)}, "
              f"equipos {', '.join(team['name'] for team in coach['teams'])}")
    print(f"  Sin entrenador: {', '.join(p.full_name for p in plan.athletes if not p.coach)}")
    print("\nRecortes")
    print(f"  {'recorte':<22}{'origen':<17}{'mov.':<7}{'tramo':>13}{'dura':>7}{'MB':>6}  {'vista':<6}{'reps':>5}  {'fecha':<17}deportista")
    for item in plan.analyses:
        clip, result = plan.clips[item["clip"]], plan.validation[item["clip"]]
        mark = "  (ya creado)" if item["clip"] in manifest.data["analyses"] else ""
        print(f"  {clip['name']:<22}{clip['source']:<17}{clip['movement']:<7}{clip['start']:>5.1f}-{clip['end']:<5.1f} s"
              f"{clip['duration_ms'] / 1000:>6.1f}s{clip['bytes'] / 1e6:>6.1f}  {result['view']:<6}{result['repetitions']:>5}  "
              f"{dates[item['clip']]:%Y-%m-%d %H:%M}  {item['athlete']}{mark}")
    total_seconds = sum(plan.clips[item["clip"]]["duration_ms"] for item in pending) / 1000
    total_mb = sum(plan.clips[item["clip"]]["bytes"] for item in pending) / 1e6
    analysis, replica = azure_estimate(plan, pending)
    print(f"\n  {len(pending)} recortes, {total_seconds:.0f} s de video y {total_mb:.1f} MB a subir")
    print(f"\nIA en Azure: ~{analysis / 60:.1f} min analizando; con el arranque en frío ({AZURE_COLD_START_SECONDS} s) y los "
          f"{AZURE_COOLDOWN_SECONDS // 60} min que la réplica sigue arriba al final, ~{replica / 60:.0f} minutos-réplica")


async def dry_run(plan: Plan, manifest: Manifest, host: str) -> None:
    problems = validate_plan(plan)
    engine = build_async_engine(DatabaseSettings(POSTGRES_HOST=host))
    try:
        async with build_session_factory(engine)() as session, session.begin():
            state = await read_state(session, plan)
    finally:
        await engine.dispose()
    problems += check_state(plan, state)
    print_dry_run(plan, state, manifest, host)
    if problems:
        print("\nNO SE PUEDE APLICAR:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("\nEn seco: no escribí nada. Todo listo para --apply.")


async def create_accounts(session_factory, plan: Plan, password: str, consent_version: int) -> list[str]:
    """Creo las cuentas nuevas en una sola transacción, verificadas y con el consentimiento vigente."""
    created_at = datetime.fromisoformat(plan.raw["accounts_created_at"])
    hasher = PasswordHasher()
    hashed = await hasher.hash(password)
    wanted = [(coach["email"], coach["full_name"], UserRole.COACH) for coach in plan.new_coaches] + \
        [(person.email, person.full_name, UserRole.ATHLETE) for person in plan.athletes]
    created = []
    async with session_factory() as session, session.begin():
        existing = set(await session.scalars(select(User.email).where(User.email.in_([email for email, _, _ in wanted]))))
        for email, full_name, role in wanted:
            if email in existing:
                continue
            session.add(User(email=email, hashed_password=hashed, full_name=full_name, role=role, is_active=True, is_verified=True,
                             video_consent_given_at=created_at, video_consent_version=consent_version, created_at=created_at))
            created.append(email)
    return created


def rpc_ok(result: tuple[dict | None, dict | None], what: str) -> dict:
    response, error = result
    if error:
        raise SeedAborted(f"{what}: {error}")
    return response


def seed_people(rpc: RpcClient, plan: Plan, sessions: dict[str, Session], manifest: Manifest) -> dict[str, tuple[str, str]]:
    """Devuelvo, por nombre, el id de la ficha y el correo de quien sube sus videos."""
    profiles: dict[str, tuple[str, str]] = {}
    admin = sessions[plan.admin_email]
    for person in plan.athletes:
        token = sessions[person.email].access_token
        response, error = rpc.call(f"{ATHLETE}/GetMyAthleteProfile", {}, token)
        if error and error["code"] == "not_found":
            response = rpc_ok(rpc.call(f"{ATHLETE}/CreateMyAthleteProfile", {"biometrics": person.biometrics()}, token), person.email)
        elif error:
            raise SeedAborted(f"{person.email}: {error}")
        athlete = response["athlete"]
        profiles[person.full_name] = (athlete["id"], person.email)
        manifest.data["accounts"][person.email] = athlete["id"]
        if person.coach:
            coach_id = rpc_ok(rpc.call("kinesiapp.account.v1.AccountService/GetMyAccount", {}, sessions[person.coach].access_token), "coach")["account"]["id"]
            if athlete.get("coachId") != coach_id:
                rpc_ok(rpc.call(f"{ATHLETE}/AssignCoach", {"athleteId": athlete["id"], "coachId": coach_id}, admin.access_token), f"assign {person.email}")
    for coach in plan.coaches:
        token = sessions[coach["email"]].access_token
        listed = rpc_ok(rpc.call(f"{MANAGED}/ListManagedAthletes", {}, token), "ListManagedAthletes")
        by_name = {athlete["displayName"]: athlete["id"] for athlete in listed.get("athletes", [])}
        for person in (p for p in plan.managed if p.owner == coach["email"]):
            if person.full_name not in by_name:
                created = rpc_ok(rpc.call(f"{MANAGED}/CreateManagedAthlete", {"fullName": person.full_name, "biometrics": person.biometrics()}, token), person.full_name)
                by_name[person.full_name] = created["athlete"]["id"]
            profiles[person.full_name] = (by_name[person.full_name], coach["email"])
            manifest.data["managed"][person.full_name] = by_name[person.full_name]
        teams = {team["name"]: team for team in rpc_ok(rpc.call(f"{TEAM}/ListTeams", {}, token), "ListTeams").get("teams", [])}
        for team in coach["teams"]:
            if team["name"] not in teams:
                teams[team["name"]] = rpc_ok(rpc.call(f"{TEAM}/CreateTeam", {"name": team["name"]}, token), team["name"])["team"]
            team_id = teams[team["name"]]["id"]
            manifest.data["teams"][team["name"]] = team_id
            for member in team["members"]:
                rpc_ok(rpc.call(f"{TEAM}/AddTeamMember", {"teamId": team_id, "athleteId": profiles[member][0]}, token), f"{team['name']} + {member}")
    manifest.save()
    return profiles


def seed_analysis(rpc: RpcClient, plan: Plan, item: dict, athlete_id: str, token: str) -> str:
    clip = plan.clips[item["clip"]]
    content = (plan.clips_dir / clip["file"]).read_bytes()
    request = {"athleteId": athlete_id, "movementType": f"MOVEMENT_TYPE_{clip['movement'].upper()}", "contentType": "video/mp4",
               "contentLength": len(content), "durationMs": clip["duration_ms"]}
    upload = rpc_ok(rpc.call(f"{ANALYSIS}/CreateVideoUpload", request, token), f"CreateVideoUpload {clip['name']}")
    target = upload["target"]
    status, _, _ = http("PUT", target["url"], content, target.get("headers", {}), upload_timeout(len(content), UPLOAD_MIN_KBPS))
    if status != 200:
        raise SeedAborted(f"PUT {clip['name']}: status {status}")
    analysis_id = rpc_ok(rpc.call(f"{ANALYSIS}/ConfirmVideoUpload", {"uploadId": upload["uploadId"]}, token), f"Confirm {clip['name']}")["analysis"]["id"]
    events, error = rpc.stream(f"{ANALYSIS}/WatchAnalysis", {"analysisId": analysis_id}, token)
    finished = events[-1][1].get("finished") if events else None
    if error or not finished or finished["status"] != "ANALYSIS_STATUS_PROCESSED":
        raise SeedAborted(f"analysis {analysis_id} ({clip['name']}) did not end PROCESSED: {error or finished}")
    return analysis_id


async def backdate(session_factory, plan: Plan, manifest: Manifest) -> None:
    dates = dict(zip((item["clip"] for item in plan.analyses), plan.analysis_dates()))
    async with session_factory() as session, session.begin():
        for clip, analysis_id in manifest.data["analyses"].items():
            await session.execute(update(JumpAnalysis).where(JumpAnalysis.id == int(analysis_id)).values(recorded_at=dates[clip]))
        team_ids = [int(team_id) for team_id in manifest.data["teams"].values()]
        teams_created_at = datetime.fromisoformat(plan.raw["teams_created_at"])
        await session.execute(update(Team).where(Team.id.in_(team_ids or [0])).values(created_at=teams_created_at))


async def apply(plan: Plan, manifest: Manifest, host: str, url: str) -> None:
    await dry_run(plan, manifest, host)
    rpc = RpcClient(url, _buf(), BACKEND / "contracts" / "proto")
    policy = rpc_ok(rpc.call("kinesiapp.system.v1.SystemService/GetClientPolicy", {}), "GetClientPolicy")
    passwords = {
        "demo": getpass.getpass("Contraseña nueva para las cuentas de demo: "),
        plan.admin_email: getpass.getpass(f"Contraseña de {plan.admin_email}: "),
        **{coach["email"]: getpass.getpass(f"Contraseña de {coach['email']}: ") for coach in plan.coaches if coach.get("existing")},
    }
    engine = build_async_engine(DatabaseSettings(POSTGRES_HOST=host))
    session_factory = build_session_factory(engine)
    try:
        created = await create_accounts(session_factory, plan, passwords["demo"], policy["videoConsentVersion"])
        print(f"Cuentas creadas: {len(created)}")
        emails = [plan.admin_email, *(coach["email"] for coach in plan.coaches), *(person.email for person in plan.athletes)]
        sessions = {email: Session(rpc, email, passwords.get(email, passwords["demo"])) for email in emails}
        profiles = seed_people(rpc, plan, sessions, manifest)
        print(f"Fichas y equipos listos: {len(profiles)} deportistas, {len(manifest.data['teams'])} equipos")
        for number, item in enumerate(plan.analyses, start=1):
            if item["clip"] in manifest.data["analyses"]:
                continue
            athlete_id, uploader = profiles[item["athlete"]]
            # Un token dura poco: lo renuevo con cada análisis entrando de nuevo
            sessions[uploader] = Session(rpc, uploader, passwords.get(uploader, passwords["demo"]))
            started = time.monotonic()
            manifest.data["analyses"][item["clip"]] = seed_analysis(rpc, plan, item, athlete_id, sessions[uploader].access_token)
            manifest.save()
            print(f"  {number:>2}/{len(plan.analyses)} {item['clip']:<22} → análisis {manifest.data['analyses'][item['clip']]} "
                  f"({time.monotonic() - started:.0f} s)", flush=True)
        await backdate(session_factory, plan, manifest)
        print("Fechas repartidas. Listo.")
    finally:
        await engine.dispose()


async def demo_targets(session, plan: Plan) -> dict:
    """Lo que es de la demo según el plan: cuentas por correo, gestionados por coach y nombre, equipos por dueño y
    nombre, y los análisis de todas esas fichas. Así lo encuentro aunque una corrida se haya cortado a la mitad."""
    coach_emails = [coach["email"] for coach in plan.coaches]
    users = {user.email: user for user in await session.scalars(select(User).where(User.email.in_(coach_emails + [p.email for p in plan.athletes])))}
    demo_users = [users[email] for email in [c["email"] for c in plan.new_coaches] + [p.email for p in plan.athletes] if email in users]
    owner_ids = {coach["email"]: users[coach["email"]].id for coach in plan.coaches if coach["email"] in users}
    managed, teams = [], []
    for coach in plan.coaches:
        if coach["email"] not in owner_ids:
            continue
        managed += list(await session.scalars(select(AthleteProfile).where(
            AthleteProfile.user_id.is_(None), AthleteProfile.coach_id == owner_ids[coach["email"]],
            AthleteProfile.full_name.in_([person["full_name"] for person in coach["managed"]]))))
        teams += list(await session.scalars(select(Team).where(
            Team.owner_id == owner_ids[coach["email"]], Team.name.in_([team["name"] for team in coach["teams"]]))))
    demo_user_ids = [user.id for user in demo_users]
    own_profiles = list(await session.scalars(select(AthleteProfile).where(AthleteProfile.user_id.in_(demo_user_ids or [0]))))
    profile_ids = [profile.id for profile in managed + own_profiles]
    analyses = list(await session.scalars(select(JumpAnalysis).where(JumpAnalysis.athlete_id.in_(profile_ids or [0])).order_by(JumpAnalysis.id)))
    # Si alguien de verdad quedó a cargo de un coach de demo, no lo borro: paro y lo reviso a mano
    strangers = list(await session.scalars(select(AthleteProfile).where(
        AthleteProfile.coach_id.in_(demo_user_ids or [0]), AthleteProfile.id.not_in(profile_ids or [0]))))
    return {"users": demo_users, "managed": managed, "own_profiles": own_profiles, "teams": teams, "analyses": analyses,
            "profile_ids": profile_ids, "strangers": strangers}


def print_cleanup(targets: dict, host: str) -> None:
    names = {profile.id: profile.full_name for profile in targets["managed"]}
    names |= {profile.id: next(u.full_name for u in targets["users"] if u.id == profile.user_id) for profile in targets["own_profiles"]}
    print(f"Host: {host}\n\nVoy a borrar")
    print(f"  análisis (con su video del bucket y su chat)   {len(targets['analyses'])}")
    for analysis in targets["analyses"]:
        print(f"    #{analysis.id:<5} {analysis.movement_type.value:<6} {analysis.status.value:<10} {names[analysis.athlete_id]}")
    print(f"  equipos                                       {len(targets['teams'])}   {', '.join(f'#{t.id} {t.name}' for t in targets['teams'])}")
    print(f"  deportistas gestionados                       {len(targets['managed'])}   {', '.join(p.full_name for p in targets['managed'])}")
    print(f"  cuentas de demo (con su ficha)                {len(targets['users'])}")
    for user in targets["users"]:
        print(f"    #{user.id:<5} {user.role.name:<8} {user.email}")
    print("  Omaira, sus datos de antes y las demás cuentas no se tocan.")


async def delete_demo_rows(session_factory, plan: Plan) -> None:
    """No hay RPC para borrar cuentas: lo que queda va en una sola transacción, en el orden de las llaves foráneas."""
    async with session_factory() as session, session.begin():
        targets = await demo_targets(session, plan)
        if targets["analyses"] or targets["strangers"]:
            raise SeedAborted("there are demo analyses left or athletes that are not demo data; nothing was deleted")
        user_ids = [user.id for user in targets["users"]]
        await session.execute(delete(Team).where(Team.id.in_([team.id for team in targets["teams"]] or [0])))
        await session.execute(delete(AthleteProfile).where(AthleteProfile.id.in_(targets["profile_ids"] or [0])))
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(user_ids or [0])))
        await session.execute(delete(User).where(User.id.in_(user_ids or [0])))


async def cleanup(plan: Plan, manifest: Manifest, host: str, url: str, execute: bool) -> None:
    engine = build_async_engine(DatabaseSettings(POSTGRES_HOST=host))
    session_factory = build_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            targets = await demo_targets(session, plan)
        print_cleanup(targets, host)
        if targets["strangers"]:
            raise SeedAborted("these athletes are not demo data but have a demo coach: "
                              + ", ".join(f"#{p.id}" for p in targets["strangers"]))
        if not execute:
            print("\nEn seco: no borré nada.")
            return
        # Los análisis van por el RPC para que el backend también quite los videos del bucket
        rpc = RpcClient(url, _buf(), BACKEND / "contracts" / "proto")
        admin = Session(rpc, plan.admin_email, getpass.getpass(f"Contraseña de {plan.admin_email}: "))
        for analysis in targets["analyses"]:
            response, error = rpc.call(f"{ANALYSIS}/DeleteAnalysis", {"analysisId": str(analysis.id)}, admin.access_token)
            if error and error["code"] != "not_found":
                raise SeedAborted(f"DeleteAnalysis {analysis.id}: {error}")
        print(f"Análisis borrados: {len(targets['analyses'])}")
        await delete_demo_rows(session_factory, plan)
        manifest.path.unlink(missing_ok=True)
        print("Datos de demostración borrados.")
    finally:
        await engine.dispose()


def _buf() -> str:
    import os
    import shutil

    return shutil.which("buf") or str(BACKEND.parent / "KinesiApp-Frontend" / "node_modules" / ".bin" / ("buf.cmd" if os.name == "nt" else "buf"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-host", required=True, help="direct Neon endpoint, never the -pooler")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--clips", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json next to the plan")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cleanup", action="store_true", help="delete the demo data; dry unless --apply is also given")
    args = parser.parse_args()
    if "-pooler" in args.target_host:
        sys.exit("Use the direct endpoint: SET TRANSACTION READ ONLY and the long transactions go better without the pooler")
    plan = Plan(args.plan, args.clips)
    manifest = Manifest(args.manifest or args.plan.with_name("manifest.json"))
    try:
        if args.cleanup:
            asyncio.run(cleanup(plan, manifest, args.target_host, args.url, execute=args.apply))
        else:
            asyncio.run(apply(plan, manifest, args.target_host, args.url) if args.apply else dry_run(plan, manifest, args.target_host))
    except SeedAborted as error:
        sys.exit(f"Aborted: {error}")


if __name__ == "__main__":
    main()
