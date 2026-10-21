"""Pruebo en la nube los servicios gRPC del backend por gRPC-Web (buf curl). Nunca imprimo contraseñas ni tokens.

Uso, desde KinesiApp-Backend:
  python -I scripts/cloud_check.py --admin-email <correo> [--athlete-email <correo> --coach-email <correo>]
      [--only account,admin,refresh,athlete,team,ai] [--origin <origen> [<origen>...]]
  python -I scripts/cloud_check.py --only analysis --athlete-email <correo> --video <mp4> --video-duration-ms <ms>
      [--keep-on-failure]   deja el análisis y su video si algo falla, para revisarlos en la base de grpc-dev
      [--upload-min-kbps N] velocidad de subida más lenta que espero en el PUT del video (1000 por defecto)
Las contraseñas las leo de KINESI_ADMIN_PASSWORD, KINESI_ATHLETE_PASSWORD y KINESI_COACH_PASSWORD, o las pido por consola.
Todo lo que creo (deportistas gestionados, equipos, fotos, análisis y su video) lo borro al final; lo que edito lo dejo como estaba.
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
DEFAULT_URL = "https://kinesiapp-backend-grpc.onrender.com"
DEFAULT_ORIGINS = [
    "https://kinesiapp.com",
    "https://www.kinesiapp.com",
    "https://kinesiapp-git-feature-grpc-frontend-solartedaniers-projects.vercel.app",
    "http://localhost:3000",
]
FOREIGN_ORIGIN = "https://example.com"
PRIVATE_IMAGES_BUCKET = "kinesiapp-dev-images"
PRIVATE_VIDEOS_BUCKET = "kinesiapp-dev-videos"
ALL_SECTIONS = ("account", "admin", "refresh", "athlete", "team", "ai", "analysis")
# Dos preguntas seguidas bastan para ver el respaldo y el historial; más gastaban la cuota diaria de Gemini
DEFAULT_QUESTIONS = [
    "¿Qué debo corregir primero?",
    "¿Cómo está mi rodilla comparada con el rango objetivo?",
]
ADMIN_SECTIONS = {"account", "admin", "refresh", "athlete", "team", "ai"}


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

    def stream(self, method: str, body: dict, token: str) -> tuple[list[tuple[float, dict]], dict | None]:
        """Devuelvo cada mensaje del stream con los segundos desde que lo abrí, para medir la primera respuesta."""
        command = [self._buf, "curl", "--protocol", "grpcweb", "--schema", str(self._schema), "-d", json.dumps(body),
                   "-H", f"authorization: Bearer {token}", f"{self._url}/{method}"]
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        decoder, pending, messages = json.JSONDecoder(), "", []
        for line in process.stdout:
            pending += line
            # buf curl escribe cada mensaje como un objeto JSON indentado; lo tomo en cuanto se cierra
            try:
                message, end = decoder.raw_decode(pending.strip())
            except json.JSONDecodeError:
                continue
            messages.append((time.monotonic() - started, message))
            pending = pending.strip()[end:]
        stderr = process.stderr.read()
        if process.wait() == 0:
            return messages, None
        try:
            error = json.loads(stderr)
        except json.JSONDecodeError:
            return messages, {"code": "unparsed", "reason": None, "message": stderr.strip()[:200]}
        reason = next(
            (_error_info_reason(d["value"]) for d in error.get("details", []) if d.get("type") == "google.rpc.ErrorInfo"),
            None,
        )
        return messages, {"code": error.get("code"), "reason": reason}


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

    def failures(self) -> int:
        return sum(1 for _, passed in self.results if not passed)

    def summary(self) -> int:
        failed = [name for name, passed in self.results if not passed]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed")
        return 1 if failed else 0


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


HTTP_TIMEOUT_SECONDS = 30


def http(
    method: str, url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = HTTP_TIMEOUT_SECONDS
) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()


def preflight(url: str, origin: str) -> tuple[int, dict]:
    status, headers, _ = http(
        "OPTIONS", url, headers={"Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"}
    )
    return status, headers


def check_cors(report: Report, label: str, url: str, origins: list[str]) -> None:
    for origin in origins:
        status, headers = preflight(url, origin)
        allowed = headers.get("access-control-allow-origin") == origin and "PUT" in headers.get("access-control-allow-methods", "")
        report.check(f"{label}: CORS preflight from {origin}", allowed, f"status={status}")
    # También reviso que un origen ajeno no pase, para notar un CORS demasiado abierto
    status, headers = preflight(url, FOREIGN_ORIGIN)
    report.check(f"{label}: CORS preflight from a foreign origin is refused", "access-control-allow-origin" not in headers, f"status={status}")


def upload_png(report: Report, label: str, upload: dict, origins: list[str]) -> bytes:
    png = tiny_png()
    target = upload["target"]
    report.check(f"{label}: upload URL points to the private bucket", PRIVATE_IMAGES_BUCKET in target["url"])
    check_cors(report, label, target["url"], origins)
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


def account_section(rpc: RpcClient, report: Report, admin: Session, origins: list[str]) -> None:
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
    png = upload_png(report, "Account avatar", upload, origins)
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
    rpc: RpcClient, report: Report, admin: Session, athlete: Session, coach: Session, origins: list[str]
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
        png = upload_png(report, "Managed avatar", upload, origins)
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


def upload_timeout(size_bytes: int, min_kbps: int) -> float:
    # Le doy al PUT el tiempo de subir el archivo a la velocidad mínima indicada, además del margen de siempre
    return HTTP_TIMEOUT_SECONDS + size_bytes * 8 / (min_kbps * 1000)


def analysis_section(
    rpc: RpcClient,
    report: Report,
    athlete: Session,
    video: Path,
    duration_ms: int,
    origins: list[str],
    keep_on_failure: bool,
    upload_min_kbps: int,
    movement: str,
    questions: list[str],
) -> None:
    service = "kinesiapp.analysis.v1.AnalysisService"
    failures_before = report.failures()
    token = athlete.access_token
    timings: list[tuple[str, float]] = []

    def timed(label: str, action):
        started = time.monotonic()
        result = action()
        timings.append((label, time.monotonic() - started))
        return result

    account, error = timed("GetMyAccount", lambda: rpc.call("kinesiapp.account.v1.AccountService/GetMyAccount", {}, token))
    if not report.check("Athlete has accepted the video consent", error is None and "videoConsentVersion" in account["account"], error):
        return
    profile, error = timed(
        "GetMyAthleteProfile", lambda: rpc.call("kinesiapp.athlete.v1.AthleteProfileService/GetMyAthleteProfile", {}, token)
    )
    if not report.check("Athlete has an athlete profile", error is None, error):
        return
    content = video.read_bytes()
    request = {"athleteId": profile["athlete"]["id"], "movementType": f"MOVEMENT_TYPE_{movement.upper()}", "contentType": "video/mp4",
               "contentLength": len(content), "durationMs": duration_ms}
    upload, error = timed("CreateVideoUpload", lambda: rpc.call(f"{service}/CreateVideoUpload", request, token))
    if not report.check("CreateVideoUpload", error is None, error):
        return
    target = upload["target"]
    report.check("Upload URL points to the private videos bucket", PRIVATE_VIDEOS_BUCKET in target["url"])
    check_cors(report, "Video", target["url"], origins)
    put_timeout = upload_timeout(len(content), upload_min_kbps)
    status, _, _ = timed(
        "PUT to the bucket", lambda: http("PUT", target["url"], content, target.get("headers", {}), put_timeout)
    )
    if not report.check("Real PUT of the video", status == 200, f"status={status} size={len(content)}"):
        return
    confirmed, error = timed("ConfirmVideoUpload", lambda: rpc.call(f"{service}/ConfirmVideoUpload", {"uploadId": upload["uploadId"]}, token))
    if not report.check("ConfirmVideoUpload creates a PENDING analysis", error is None and confirmed["analysis"]["status"] == "ANALYSIS_STATUS_PENDING", error):
        return
    analysis_id = confirmed["analysis"]["id"]
    video_url = ""
    try:
        again, error = rpc.call(f"{service}/ConfirmVideoUpload", {"uploadId": upload["uploadId"]}, token)
        report.check("Confirming again returns the same analysis", error is None and again["analysis"]["id"] == analysis_id, error)
        events, error = rpc.stream(f"{service}/WatchAnalysis", {"analysisId": analysis_id}, token)
        stages = [message["progress"].get("stage") for _, message in events if "progress" in message]
        finished = events[-1][1].get("finished") if events else None
        if events:
            timings.append(("WatchAnalysis first event", events[0][0]))
            timings.append(("WatchAnalysis until the result", events[-1][0]))
        report.check(
            "WatchAnalysis streams progress and ends PROCESSED",
            error is None and finished and finished["status"] == "ANALYSIS_STATUS_PROCESSED",
            error
            or f"{len(events)} events, stages={list(dict.fromkeys(filter(None, stages)))}, "
            f"status={finished and finished.get('status')}, failure={finished and finished.get('failureReason')}, "
            f"risk={finished and finished.get('riskLevel')}",
        )
        detail, error = rpc.call(f"{service}/GetAnalysis", {"analysisId": analysis_id}, token)
        samples = len(detail["analysis"].get("angleSamples", [])) if detail else 0
        report.check("GetAnalysis has angle samples and risk assessment", error is None and samples and "riskAssessment" in detail["analysis"], error or f"{samples} samples")
        playback, error = timed("GetVideoPlaybackUrl", lambda: rpc.call(f"{service}/GetVideoPlaybackUrl", {"analysisId": analysis_id}, token))
        video_url = playback["video"]["url"] if playback else ""
        status, _, body = http("GET", video_url, headers={"Range": "bytes=0-15"}) if video_url else (0, {}, b"")
        report.check("Playback URL serves byte ranges of the same video", status == 206 and body == content[:16], f"status={status}")
        listed, error = rpc.call(f"{service}/ListAthleteAnalyses", {"athleteId": profile["athlete"]["id"], "page": {"pageSize": 5}}, token)
        report.check("ListAthleteAnalyses shows it first", error is None and listed["analyses"][0]["id"] == analysis_id, error)

        opening, error = rpc.stream("kinesiapp.chat.v1.ChatService/StartConversation", {"analysisId": analysis_id}, token)
        deltas = [m for _, m in opening if "textDelta" in m]
        if opening:
            timings.append(("StartConversation first delta", opening[0][0]))
            timings.append(("StartConversation total", opening[-1][0]))
        report.check("StartConversation streams the explanation", error is None and deltas and "assistantMessage" in opening[-1][1], error or f"{len(deltas)} deltas")
        for number, question in enumerate(questions, start=1):
            answer, error = rpc.stream(
                "kinesiapp.chat.v1.ChatService/SendMessage", {"analysisId": analysis_id, "content": question}, token
            )
            if answer:
                timings.append((f"SendMessage {number} first event", answer[0][0]))
                timings.append((f"SendMessage {number} total", answer[-1][0]))
            report.check(
                f"SendMessage {number} streams the question and the answer",
                error is None and answer and "userMessage" in answer[0][1] and "assistantMessage" in answer[-1][1],
                error or f"{len(answer)} events",
            )
        history, error = rpc.call("kinesiapp.chat.v1.ChatService/ListMessages", {"analysisId": analysis_id}, token)
        asked = [m["content"] for m in (history or {}).get("messages", []) if m.get("role") == "CHAT_ROLE_USER"]
        answered = [m for m in (history or {}).get("messages", []) if m.get("role") == "CHAT_ROLE_ASSISTANT"]
        report.check(
            "Each question is saved once and answered",
            error is None and asked == questions and len(answered) == len(questions) + 1,
            error or f"{len(asked)} questions, {len(answered)} assistant messages",
        )
    finally:
        if keep_on_failure and report.failures() > failures_before:
            print(f"\nKept analysis {analysis_id} and its video for inspection; delete it with DeleteAnalysis when done")
            return
        _, error = timed("DeleteAnalysis", lambda: rpc.call(f"{service}/DeleteAnalysis", {"analysisId": analysis_id}, token))
        report.check("DeleteAnalysis", error is None, error)
        _, error = rpc.call(f"{service}/GetAnalysis", {"analysisId": analysis_id}, token)
        report.check("Deleted analysis is NOT_FOUND", error and error["code"] == "not_found", error)
    if video_url:
        check_object_gone(report, "Deleted analysis video", video_url)
    print("\nTimings")
    for label, seconds in timings:
        print(f"  {label:<34} {seconds:6.1f} s")


def _password(variable: str, label: str) -> str:
    return os.environ.pop(variable, "") or getpass.getpass(f"{label} password: ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--origin", dest="origins", nargs="+", default=DEFAULT_ORIGINS, help="frontend origins that must pass the bucket CORS")
    parser.add_argument("--admin-email")
    parser.add_argument("--athlete-email")
    parser.add_argument("--coach-email")
    parser.add_argument("--only", default=",".join(ALL_SECTIONS))
    parser.add_argument("--video", type=Path)
    parser.add_argument("--video-duration-ms", type=int)
    parser.add_argument("--movement", choices=("jump", "squat"), default="squat", help="movement recorded in --video")
    parser.add_argument("--question", dest="questions", action="append", help="chat question; repeat it to ask several")
    parser.add_argument("--keep-on-failure", action="store_true")
    parser.add_argument("--upload-min-kbps", type=int, default=1000, help="slowest upload speed to wait for, in kbit/s")
    args = parser.parse_args()
    sections = set(args.only.split(","))
    if sections & ADMIN_SECTIONS and not args.admin_email:
        parser.error("these sections need --admin-email")
    if "analysis" in sections and not (args.athlete_email and args.video and args.video_duration_ms):
        parser.error("analysis needs --athlete-email, --video and --video-duration-ms")
    if sections & {"athlete", "team"} and not (args.athlete_email and args.coach_email):
        parser.error("athlete and team need --athlete-email and --coach-email")

    buf = shutil.which("buf") or str(BACKEND.parent / "KinesiApp-Frontend" / "node_modules" / ".bin" / ("buf.cmd" if os.name == "nt" else "buf"))
    rpc = RpcClient(args.url, buf, BACKEND / "contracts" / "proto")
    report = Report()
    admin = Session(rpc, args.admin_email, _password("KINESI_ADMIN_PASSWORD", "Admin")) if sections & ADMIN_SECTIONS else None
    if "account" in sections:
        account_section(rpc, report, admin, args.origins)
    if "admin" in sections:
        admin_section(rpc, report, admin)
    athlete = None
    if sections & {"athlete", "team", "analysis"}:
        athlete = Session(rpc, args.athlete_email, _password("KINESI_ATHLETE_PASSWORD", "Athlete"))
    if sections & {"athlete", "team"}:
        coach = Session(rpc, args.coach_email, _password("KINESI_COACH_PASSWORD", "Coach"))
        managed = athlete_section(rpc, report, admin, athlete, coach, args.origins) if "athlete" in sections else None
        managed_id, avatar_url = managed if managed else (None, None)
        try:
            if "team" in sections:
                team_section(rpc, report, admin, athlete, coach, managed_id)
        finally:
            if managed_id:
                delete_managed_athlete(rpc, report, coach, managed_id, avatar_url)
    if "ai" in sections:
        ai_section(rpc, report, admin)
    if "analysis" in sections:
        analysis_section(rpc, report, athlete, args.video, args.video_duration_ms, args.origins, args.keep_on_failure, args.upload_min_kbps,
                         args.movement, args.questions or DEFAULT_QUESTIONS)
    if "refresh" in sections:
        refresh_section(rpc, report, admin)
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
