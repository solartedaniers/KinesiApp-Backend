"""Pruebo en la nube los servicios gRPC del backend por gRPC-Web (buf curl). Nunca imprimo contraseñas ni tokens.

Uso, desde KinesiApp-Backend:
  python -I scripts/cloud_check.py --admin-email <correo> [--athlete-email <correo> --coach-email <correo>]
      [--only account,admin,refresh,athlete,team,ai]
Las contraseñas las leo de KINESI_ADMIN_PASSWORD, KINESI_ATHLETE_PASSWORD y KINESI_COACH_PASSWORD, o las pido por consola.
Todo lo que creo (deportistas gestionados, equipos, fotos) lo borro al final; lo que edito lo dejo como estaba.
"""

import argparse
import base64
import getpass
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://kinesiapp-backend-prueva.onrender.com"
DEFAULT_ORIGIN = "https://kinesiapp-git-feature-grpc-spike-solartedaniers-projects.vercel.app"
PRIVATE_IMAGES_BUCKET = "kinesiapp-dev-images"
ALL_SECTIONS = ("account", "admin", "refresh", "athlete", "team", "ai")


class Session:
    def __init__(self, client: "RpcClient", email: str, password: str) -> None:
        response, error = client.call("kinesiapp.auth.v1.AuthService/Login", {"email": email, "password": password})
        if error:
            sys.exit(f"login failed for {email}: {error}")
        self.email = email
        self.access_token = response["session"]["accessToken"]
        self.refresh_token = response["session"]["refreshToken"]


class RpcClient:
    """Llamo a un RPC con buf curl y devuelvo (respuesta, error) con el reason de google.rpc.ErrorInfo ya decodificado."""

    def __init__(self, url: str, buf: str, schema: Path) -> None:
        self._url = url
        self._buf = buf
        self._schema = schema

    def call(self, method: str, body: dict, token: str | None = None) -> tuple[dict | None, dict | None]:
        command = [self._buf, "curl", "--protocol", "grpcweb", "--schema", str(self._schema), "-d", json.dumps(body)]
        if token:
            command += ["-H", f"authorization: Bearer {token}"]
        command.append(f"{self._url}/{method}")
        out = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0:
            return json.loads(out.stdout or "{}"), None
        try:
            error = json.loads(out.stderr)
        except json.JSONDecodeError:
            return None, {"code": "unparsed", "reason": None, "message": out.stderr.strip()[:200]}
        reason = next(
            (_error_info_reason(d["value"]) for d in error.get("details", []) if d.get("type") == "google.rpc.ErrorInfo"),
            None,
        )
        return None, {"code": error.get("code"), "reason": reason}


def _error_info_reason(value: str) -> str:
    # buf curl entrega el detalle en base64 sin padding; reason es el campo 1 de ErrorInfo
    raw = base64.b64decode(value + "=" * (-len(value) % 4))
    return raw[2 : 2 + raw[1]].decode() if raw and raw[0] == 0x0A else ""


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool]] = []

    def check(self, name: str, ok: object, detail: object = "") -> bool:
        passed = bool(ok)
        self.results.append((name, passed))
        print(("PASS " if passed else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
        return passed

    def summary(self) -> int:
        failed = [name for name, passed in self.results if not passed]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed")
        return 1 if failed else 0


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def http(method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def upload_png(report: Report, label: str, upload: dict, origin: str) -> bytes:
    png = tiny_png()
    target = upload["target"]
    report.check(f"{label}: upload URL points to the private bucket", PRIVATE_IMAGES_BUCKET in target["url"])
    status, headers, _ = http(
        "OPTIONS", target["url"], headers={"Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"}
    )
    report.check(f"{label}: CORS preflight from the preview", headers.get("access-control-allow-origin") == origin, f"status={status}")
    status, _, _ = http("PUT", target["url"], png + b"x", target.get("headers", {}))
    report.check(f"{label}: PUT with another size is rejected by the signature", status >= 400, f"status={status}")
    status, _, _ = http("PUT", target["url"], png, target.get("headers", {}))
    report.check(f"{label}: real PUT to the private bucket", status == 200, f"status={status}")
    return png


def check_signed_avatar(report: Report, label: str, avatar_url: str, png: bytes) -> None:
    status, _, body = http("GET", avatar_url)
    report.check(f"{label}: signed read URL returns the same bytes", status == 200 and body == png, f"status={status}")
    status, _, _ = http("GET", avatar_url.split("?", 1)[0])
    report.check(f"{label}: object is private without signature", status in (401, 403), f"status={status}")


def check_object_gone(report: Report, label: str, avatar_url: str) -> None:
    time.sleep(1)
    status, _, _ = http("GET", avatar_url)
    report.check(f"{label}: object is gone from the bucket", status in (403, 404), f"status={status}")


def account_section(rpc: RpcClient, report: Report, admin: Session, origin: str) -> None:
    token = admin.access_token
    account, error = rpc.call("kinesiapp.account.v1.AccountService/GetMyAccount", {}, token)
    if not report.check("GetMyAccount", error is None, error):
        return
    original_name = account["account"]["fullName"]
    renamed, error = rpc.call("kinesiapp.account.v1.AccountService/UpdateMyProfile", {"fullName": "Cuenta Prueba Nube"}, token)
    report.check("UpdateMyProfile", error is None and renamed["account"]["fullName"] == "Cuenta Prueba Nube", error)
    _, error = rpc.call("kinesiapp.account.v1.AccountService/UpdateMyProfile", {"fullName": "Nombre 123"}, token)
    report.check("UpdateMyProfile rejects digits", error and error["reason"] == "BAD_REQUEST", error)
    rpc.call("kinesiapp.account.v1.AccountService/UpdateMyProfile", {"fullName": original_name}, token)

    if "avatar" in account["account"]:
        report.check("Avatar flow skipped: the account already has an avatar", False)
        return
    upload, error = rpc.call(
        "kinesiapp.account.v1.AccountService/CreateAvatarUpload",
        {"contentType": "IMAGE_CONTENT_TYPE_PNG", "contentLength": len(tiny_png())},
        token,
    )
    if not report.check("CreateAvatarUpload", error is None, error):
        return
    _, error = rpc.call("kinesiapp.account.v1.AccountService/ConfirmAvatarUpload", {"uploadId": upload["uploadId"]}, token)
    report.check("Confirm before PUT is UPLOAD_NOT_FOUND", error and error["reason"] == "UPLOAD_NOT_FOUND", error)
    png = upload_png(report, "Account avatar", upload, origin)
    confirmed, error = rpc.call("kinesiapp.account.v1.AccountService/ConfirmAvatarUpload", {"uploadId": upload["uploadId"]}, token)
    if not report.check("ConfirmAvatarUpload", error is None and "avatar" in confirmed["account"], error):
        return
    avatar_url = confirmed["account"]["avatar"]["url"]
    check_signed_avatar(report, "Account avatar", avatar_url, png)
    deleted, error = rpc.call("kinesiapp.account.v1.AccountService/DeleteMyAvatar", {}, token)
    report.check("DeleteMyAvatar", error is None and "avatar" not in deleted["account"], error)
    check_object_gone(report, "Account avatar", avatar_url)


def admin_section(rpc: RpcClient, report: Report, admin: Session) -> None:
    token = admin.access_token
    page, error = rpc.call("kinesiapp.admin.v1.UserAdminService/ListUsers", {"page": {"pageSize": 2}}, token)
    first = [u["id"] for u in page["users"]] if page else []
    report.check("ListUsers page 1", error is None and len(first) == 2 and page["page"].get("nextPageToken"), first)
    page2, error = rpc.call(
        "kinesiapp.admin.v1.UserAdminService/ListUsers", {"page": {"pageSize": 2, "pageToken": page["page"]["nextPageToken"]}}, token
    )
    second = [u["id"] for u in page2["users"]] if page2 else []
    report.check("ListUsers page 2 continues after page 1", second and int(second[0]) > int(first[-1]), second)
    _, error = rpc.call("kinesiapp.admin.v1.UserAdminService/ListUsers", {"page": {"pageToken": "not-a-token"}}, token)
    report.check("ListUsers rejects a forged page token", error and error["reason"] == "BAD_REQUEST", error)
    me, _ = rpc.call("kinesiapp.account.v1.AccountService/GetMyAccount", {}, token)
    _, error = rpc.call(
        "kinesiapp.admin.v1.UserAdminService/UpdateUserRole", {"userId": me["account"]["id"], "role": "USER_ROLE_COACH"}, token
    )
    report.check("Admin cannot modify own account", error and error["reason"] == "CANNOT_MODIFY_OWN_ACCOUNT", error)
    _, error = rpc.call("kinesiapp.admin.v1.UserAdminService/GetUser", {"userId": "999999999"}, token)
    report.check("GetUser unknown is NOT_FOUND", error and error["code"] == "not_found", error)
    _, error = rpc.call("kinesiapp.admin.v1.UserAdminService/ListUsers", {})
    report.check("Admin RPC without token is UNAUTHENTICATED", error and error["code"] == "unauthenticated", error)


def refresh_section(rpc: RpcClient, report: Report, session: Session) -> None:
    method = "kinesiapp.auth.v1.AuthService/RefreshSession"
    renewed, error = rpc.call(method, {"refreshToken": session.refresh_token})
    if not report.check("RefreshSession first use", error is None, error):
        return
    _, error = rpc.call(method, {"refreshToken": session.refresh_token})
    report.check("RefreshSession reuse is rejected", error and error["reason"] == "INVALID_REFRESH_TOKEN", error)
    fresh = renewed["session"]["refreshToken"]
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda _: rpc.call(method, {"refreshToken": fresh}), range(2)))
    passed = [response for response, error in outcomes if error is None]
    rejected = [error["reason"] for _, error in outcomes if error is not None]
    report.check("Two simultaneous refreshes: one passes, one fails", len(passed) == 1 and rejected == ["INVALID_REFRESH_TOKEN"], rejected)
    for response in passed:
        rpc.call("kinesiapp.auth.v1.AuthService/Logout", {"refreshToken": response["session"]["refreshToken"]})


BIOMETRICS = {"gender": "GENDER_MALE", "heightCm": 172.0, "weightKg": 68.0, "birthDate": {"year": 2009, "month": 8, "day": 1}}


def athlete_section(
    rpc: RpcClient, report: Report, admin: Session, athlete: Session, coach: Session, origin: str
) -> tuple[str, str | None] | None:
    # Devuelvo el deportista gestionado y la URL de su foto para que equipos los use y el final los borre
    profiles = "kinesiapp.athlete.v1.AthleteProfileService"
    managed = "kinesiapp.athlete.v1.ManagedAthleteService"

    mine, error = rpc.call(f"{profiles}/GetMyAthleteProfile", {}, athlete.access_token)
    if error and error["code"] == "not_found":
        mine, error = rpc.call(f"{profiles}/CreateMyAthleteProfile", {"biometrics": BIOMETRICS}, athlete.access_token)
        report.check("Onboarding: CreateMyAthleteProfile", error is None, error)
    if not report.check("GetMyAthleteProfile", error is None, error):
        return None
    profile = mine["athlete"]
    _, error = rpc.call(f"{profiles}/CreateMyAthleteProfile", {"biometrics": BIOMETRICS}, athlete.access_token)
    report.check("Second onboarding is PROFILE_ALREADY_EXISTS", error and error["reason"] == "PROFILE_ALREADY_EXISTS", error)
    original_weight = profile["biometrics"]["weightKg"]
    updated, error = rpc.call(
        f"{profiles}/UpdateMyAthleteProfile", {"biometrics": {"weightKg": original_weight + 1}}, athlete.access_token
    )
    report.check(
        "UpdateMyAthleteProfile changes only the weight",
        error is None
        and updated["athlete"]["biometrics"]["weightKg"] == original_weight + 1
        and updated["athlete"]["biometrics"]["heightCm"] == profile["biometrics"]["heightCm"],
        error,
    )
    rpc.call(f"{profiles}/UpdateMyAthleteProfile", {"biometrics": {"weightKg": original_weight}}, athlete.access_token)
    _, error = rpc.call(
        f"{profiles}/UpdateMyAthleteProfile", {"biometrics": {"birthDate": {"year": 2099, "month": 1, "day": 1}}}, athlete.access_token
    )
    report.check("Future birth date is rejected", error and error["reason"] == "BAD_REQUEST", error)
    _, error = rpc.call(f"{profiles}/CreateMyAthleteProfile", {"biometrics": BIOMETRICS}, coach.access_token)
    report.check("A coach has no own athlete profile (FORBIDDEN)", error and error["reason"] == "FORBIDDEN", error)

    def visible(session: Session, athlete_id: str) -> tuple[dict | None, dict | None]:
        return rpc.call(f"{profiles}/GetAthleteProfile", {"athleteId": athlete_id}, session.access_token)

    _, error = visible(athlete, profile["id"])
    report.check("Directory: the athlete sees their own profile", error is None, error)
    _, error = visible(admin, profile["id"])
    report.check("Directory: the admin sees any profile", error is None, error)
    if profile.get("coachId") != coach_id(rpc, coach):
        _, error = visible(coach, profile["id"])
        report.check("Directory: a coach cannot see someone else's athlete", error and error["reason"] == "FORBIDDEN", error)
    listing, error = rpc.call(f"{profiles}/ListAthletes", {"page": {"pageSize": 1}}, admin.access_token)
    report.check("ListAthletes paginates for the admin", error is None and len(listing["athletes"]) == 1, error)
    _, error = rpc.call(f"{profiles}/ListAthletes", {}, coach.access_token)
    report.check("ListAthletes is FORBIDDEN for a coach", error and error["reason"] == "FORBIDDEN", error)
    _, error = rpc.call(
        f"{profiles}/AssignCoach", {"athleteId": profile["id"], "coachId": profile.get("userId")}, admin.access_token
    )
    report.check("AssignCoach to a non coach is INVALID_ROLE_ASSIGNMENT", error and error["reason"] == "INVALID_ROLE_ASSIGNMENT", error)
    _, error = rpc.call(f"{profiles}/ListCoachedAthletes", {}, coach.access_token)
    report.check("ListCoachedAthletes for the coach", error is None, error)

    created, error = rpc.call(f"{managed}/CreateManagedAthlete", {"fullName": "Gestionado Prueba Nube", "biometrics": BIOMETRICS}, coach.access_token)
    if not report.check("CreateManagedAthlete", error is None and created["athlete"].get("isManaged"), error):
        return None
    managed_id = created["athlete"]["id"]
    _, error = visible(coach, managed_id)
    report.check("Directory: the coach sees their managed athlete", error is None, error)
    _, error = visible(athlete, managed_id)
    report.check("Directory: an athlete cannot see a managed athlete", error and error["reason"] == "FORBIDDEN", error)
    _, error = rpc.call(f"{managed}/CreateManagedAthlete", {"fullName": "R2D2", "biometrics": BIOMETRICS}, coach.access_token)
    report.check("CreateManagedAthlete rejects an invalid name", error and error["reason"] == "BAD_REQUEST", error)
    updated, error = rpc.call(
        f"{managed}/UpdateManagedAthlete", {"athleteId": managed_id, "fullName": "Gestionado Editado", "biometrics": {"heightCm": 175.0}}, coach.access_token
    )
    report.check(
        "UpdateManagedAthlete",
        error is None and updated["athlete"]["displayName"] == "Gestionado Editado" and updated["athlete"]["biometrics"]["heightCm"] == 175.0,
        error,
    )
    listed, error = rpc.call(f"{managed}/ListManagedAthletes", {}, coach.access_token)
    report.check("ListManagedAthletes includes it", error is None and managed_id in [a["id"] for a in listed["athletes"]], error)
    _, error = rpc.call(f"{managed}/ListManagedAthletes", {}, athlete.access_token)
    report.check("ManagedAthleteService is FORBIDDEN for an athlete", error and error["reason"] == "FORBIDDEN", error)

    avatar_url = None
    upload, error = rpc.call(
        f"{managed}/CreateManagedAthleteAvatarUpload",
        {"athleteId": managed_id, "contentType": "IMAGE_CONTENT_TYPE_PNG", "contentLength": len(tiny_png())},
        coach.access_token,
    )
    if report.check("CreateManagedAthleteAvatarUpload", error is None, error):
        png = upload_png(report, "Managed avatar", upload, origin)
        confirmed, error = rpc.call(
            f"{managed}/ConfirmManagedAthleteAvatarUpload", {"athleteId": managed_id, "uploadId": upload["uploadId"]}, coach.access_token
        )
        if report.check("ConfirmManagedAthleteAvatarUpload", error is None and "avatar" in confirmed["athlete"], error):
            avatar_url = confirmed["athlete"]["avatar"]["url"]
            check_signed_avatar(report, "Managed avatar", avatar_url, png)
    return managed_id, avatar_url


def coach_id(rpc: RpcClient, coach: Session) -> str:
    account, _ = rpc.call("kinesiapp.account.v1.AccountService/GetMyAccount", {}, coach.access_token)
    return account["account"]["id"]


def delete_managed_athlete(rpc: RpcClient, report: Report, coach: Session, managed_id: str, avatar_url: str | None) -> None:
    method = "kinesiapp.athlete.v1.ManagedAthleteService/DeleteManagedAthlete"
    _, error = rpc.call(method, {"athleteId": managed_id}, coach.access_token)
    report.check("DeleteManagedAthlete", error is None, error)
    _, error = rpc.call(method, {"athleteId": managed_id}, coach.access_token)
    report.check("Deleting it again is NOT_FOUND", error and error["code"] == "not_found", error)
    if avatar_url:
        check_object_gone(report, "Cascade delete: managed avatar", avatar_url)


def team_section(rpc: RpcClient, report: Report, admin: Session, athlete: Session, coach: Session, managed_id: str | None) -> None:
    teams = "kinesiapp.team.v1.TeamService"
    name = f"Prueba Nube {int(time.time())}"
    created, error = rpc.call(f"{teams}/CreateTeam", {"name": f"  {name} "}, coach.access_token)
    if not report.check("CreateTeam trims the name", error is None and created["team"]["name"] == name, error):
        return
    team_id = created["team"]["id"]
    try:
        _, error = rpc.call(f"{teams}/CreateTeam", {"name": name}, coach.access_token)
        report.check("Duplicate name is TEAM_NAME_TAKEN", error and error["reason"] == "TEAM_NAME_TAKEN", error)
        _, error = rpc.call(f"{teams}/CreateTeam", {"name": "   "}, coach.access_token)
        report.check("Blank name is rejected", error and error["reason"] == "BAD_REQUEST", error)
        with ThreadPoolExecutor(3) as pool:
            race = list(pool.map(lambda _: rpc.call(f"{teams}/CreateTeam", {"name": f"{name} B"}, coach.access_token), range(3)))
        winners = [response["team"]["id"] for response, error in race if error is None]
        losers = [error["reason"] for _, error in race if error is not None]
        report.check("Simultaneous creations leave a single team", len(winners) == 1 and set(losers) == {"TEAM_NAME_TAKEN"}, losers)
        for winner in winners:
            rpc.call(f"{teams}/DeleteTeam", {"teamId": winner}, coach.access_token)

        renamed, error = rpc.call(f"{teams}/RenameTeam", {"teamId": team_id, "name": f"{name} R"}, coach.access_token)
        report.check("RenameTeam", error is None and renamed["team"]["name"] == f"{name} R", error)
        _, error = rpc.call(f"{teams}/GetTeam", {"teamId": team_id}, admin.access_token)
        report.check("The admin sees any team", error is None, error)
        _, error = rpc.call(f"{teams}/ListTeams", {}, athlete.access_token)
        report.check("TeamService is FORBIDDEN for an athlete", error and error["reason"] == "FORBIDDEN", error)

        own_profile, _ = rpc.call("kinesiapp.athlete.v1.AthleteProfileService/GetMyAthleteProfile", {}, athlete.access_token)
        if own_profile and own_profile["athlete"].get("coachId") != coach_id(rpc, coach):
            _, error = rpc.call(
                f"{teams}/AddTeamMember", {"teamId": team_id, "athleteId": own_profile["athlete"]["id"]}, coach.access_token
            )
            report.check("Another coach's athlete is INVALID_TEAM_MEMBER", error and error["reason"] == "INVALID_TEAM_MEMBER", error)
        if managed_id:
            for attempt in ("AddTeamMember", "AddTeamMember (idempotent)"):
                added, error = rpc.call(f"{teams}/AddTeamMember", {"teamId": team_id, "athleteId": managed_id}, coach.access_token)
                report.check(attempt, error is None and added["team"].get("athleteIds") == [managed_id], error)
            removed, error = rpc.call(f"{teams}/RemoveTeamMember", {"teamId": team_id, "athleteId": managed_id}, coach.access_token)
            report.check("RemoveTeamMember", error is None and not removed["team"].get("athleteIds"), error)
            rpc.call(f"{teams}/AddTeamMember", {"teamId": team_id, "athleteId": managed_id}, coach.access_token)
    finally:
        _, error = rpc.call(f"{teams}/DeleteTeam", {"teamId": team_id}, coach.access_token)
        report.check("DeleteTeam", error is None, error)
        _, error = rpc.call(f"{teams}/GetTeam", {"teamId": team_id}, coach.access_token)
        report.check("Deleted team is NOT_FOUND", error and error["code"] == "not_found", error)


def ai_section(rpc: RpcClient, report: Report, session: Session) -> None:
    # Llamo dos veces: la primera puede incluir el arranque en frío de la IA y la segunda mide la ida y vuelta en caliente
    for label in ("first", "second"):
        started = time.monotonic()
        response, error = rpc.call("kinesiapp.system.v1.SystemService/WakeUpAi", {}, session.access_token)
        elapsed = f"{time.monotonic() - started:.1f}s"
        report.check(f"WakeUpAi {label} call is READY", error is None and response.get("state") == "AI_STATE_READY", error or elapsed)


def _password(variable: str, label: str) -> str:
    return os.environ.pop(variable, "") or getpass.getpass(f"{label} password: ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--athlete-email")
    parser.add_argument("--coach-email")
    parser.add_argument("--only", default=",".join(ALL_SECTIONS))
    args = parser.parse_args()
    sections = set(args.only.split(","))
    if sections & {"athlete", "team"} and not (args.athlete_email and args.coach_email):
        parser.error("athlete and team need --athlete-email and --coach-email")

    buf = shutil.which("buf") or str(BACKEND.parent / "KinesiApp-Frontend" / "node_modules" / ".bin" / ("buf.cmd" if os.name == "nt" else "buf"))
    rpc = RpcClient(args.url, buf, BACKEND / "contracts" / "proto")
    report = Report()
    admin = Session(rpc, args.admin_email, _password("KINESI_ADMIN_PASSWORD", "Admin"))
    if "account" in sections:
        account_section(rpc, report, admin, args.origin)
    if "admin" in sections:
        admin_section(rpc, report, admin)
    if sections & {"athlete", "team"}:
        athlete = Session(rpc, args.athlete_email, _password("KINESI_ATHLETE_PASSWORD", "Athlete"))
        coach = Session(rpc, args.coach_email, _password("KINESI_COACH_PASSWORD", "Coach"))
        managed = athlete_section(rpc, report, admin, athlete, coach, args.origin) if "athlete" in sections else None
        managed_id, avatar_url = managed if managed else (None, None)
        try:
            if "team" in sections:
                team_section(rpc, report, admin, athlete, coach, managed_id)
        finally:
            if managed_id:
                delete_managed_athlete(rpc, report, coach, managed_id, avatar_url)
    if "ai" in sections:
        ai_section(rpc, report, admin)
    if "refresh" in sections:
        refresh_section(rpc, report, admin)
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
