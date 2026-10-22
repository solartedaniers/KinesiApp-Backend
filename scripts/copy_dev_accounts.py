"""Copio cuentas elegidas de grpc-dev a otra branch de Neon (production) con sus datos y archivos.

Uso, desde KinesiApp-Backend (la base de origen es la del .env; el destino usa las mismas credenciales):
  python -I scripts/copy_dev_accounts.py --target-host <endpoint directo> --email <correo> [--email ...]
      [--update-existing <correo>]   la cuenta ya existe en el destino: conservo su id y la piso con la de origen
      [--replace-existing <correo>]  la cuenta del destino es otra: la borro con todo lo suyo y copio la de origen
      [--apply]                      sin esto corro en seco, en transacciones READ ONLY

Copio cada cuenta con su mismo hash de contraseña, más sus perfiles de deportista (el propio y los que gestiona),
análisis con mediciones, chats y equipos. Los videos, fotos y logos van del bucket de origen al de destino y
reescribo sus URLs. No copio refresh tokens: el destino tiene otra clave JWT.

Es idempotente: reconozco lo ya copiado por llaves naturales (correo, video, perfil, equipo, conversación) y la
segunda corrida no hace nada. Todo lo de la base va en una transacción, que solo se confirma si al final ninguna
URL del destino apunta fuera de los buckets de destino. Nunca imprimo hashes, contraseñas ni credenciales.
"""

import argparse
import asyncio
import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings.database import DatabaseSettings  # noqa: E402
from app.settings.storage import StorageSettings  # noqa: E402

FILE_COLUMNS = (("users", "avatar_url"), ("athlete_profiles", "avatar_url"), ("teams", "logo_url"), ("jump_analyses", "video_reference"))
# Columnas que comparo en seco sin mostrar su valor
SECRET_COLUMNS = {"hashed_password", "verification_code_hash", "password_reset_code_hash"}
SHOWN_ACCOUNT_COLUMNS = ("role", "is_active", "is_verified", "full_name", "avatar_url", "video_consent_version", "created_at")


class CopyAborted(Exception):
    """Algo del plan no es seguro de aplicar; no escribo nada."""


@dataclass(frozen=True)
class Buckets:
    endpoint: str
    source_images: str
    source_videos: str
    target_images: str
    target_videos: str

    def target_prefixes(self) -> tuple[str, str]:
        return (self._base(self.target_images), self._base(self.target_videos))

    def _base(self, bucket: str) -> str:
        return f"{self.endpoint.rstrip('/')}/{bucket}/"

    def rewrite(self, url: str | None, athlete_id: int | str | None = None) -> tuple[str | None, tuple[str, str, str, str] | None]:
        """Devuelvo la URL de destino y la copia (bucket y clave de origen y destino) que hay que hacer."""
        if url is None:
            return None, None
        for source, target in ((self.source_images, self.target_images), (self.source_videos, self.target_videos)):
            if url.startswith(self._base(source)):
                key = url.removeprefix(self._base(source))
                new_key = key
                # Los videos van en videos/{athlete_id}/{uuid}; el deportista cambia de id en el destino
                if athlete_id is not None:
                    parts = key.split("/")
                    if len(parts) != 3 or parts[0] != "videos":
                        raise CopyAborted(f"Unexpected video key: {key}")
                    new_key = f"videos/{athlete_id}/{parts[2]}"
                return self._base(target) + new_key, (source, key, target, new_key)
        raise CopyAborted(f"URL outside the source buckets: {url}")


@dataclass(frozen=True)
class AccountDecision:
    action: str  # insert | keep | update | replace
    target_id: int | None


def decide_account(source: dict, target: dict | None, update: set[str], replace: set[str]) -> AccountDecision:
    """Decido qué hacer con una cuenta según lo que ya hay en el destino. Nunca piso un correo sin permiso."""
    email = source["email"]
    if target is None:
        return AccountDecision("insert", None)
    # Si el hash y la fecha de creación coinciden, es la misma cuenta ya copiada
    if target["hashed_password"] == source["hashed_password"] and target["created_at"] == source["created_at"]:
        return AccountDecision("keep", target["id"])
    if email in update:
        return AccountDecision("update", target["id"])
    if email in replace:
        return AccountDecision("replace", target["id"])
    raise CopyAborted(f"{email} already exists in the target (id {target['id']}); pass --update-existing or --replace-existing")


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    copies: list[tuple[str, str, str, str]] = field(default_factory=list)

    def add(self, line: str) -> None:
        self.lines.append(line)
        print(line)


async def connect(settings: DatabaseSettings, host: str) -> asyncpg.Connection:
    # Sin caché de sentencias porque el host de origen puede ser el -pooler
    return await asyncpg.connect(
        host=host, port=settings.POSTGRES_PORT, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD.get_secret_value(), database=settings.POSTGRES_DB,
        ssl=ssl.create_default_context(), statement_cache_size=0, timeout=30,
    )


async def columns_of(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch("select column_name from information_schema.columns where table_schema='public' and table_name=$1 order by ordinal_position", table)
    return [r[0] for r in rows]


class AccountCopier:
    def __init__(self, source: asyncpg.Connection, target: asyncpg.Connection, buckets: Buckets, apply: bool, report: Report):
        self._source = source
        self._target = target
        self._buckets = buckets
        self._apply = apply
        self._report = report
        self._target_columns: dict[str, list[str]] = {}
        self._noted_missing: set[str] = set()
        self._fake_id = 0

    async def run(self, emails: list[str], update: set[str], replace: set[str]) -> None:
        source_version = await self._source.fetchval("select version_num from alembic_version")
        target_version = await self._target.fetchval("select version_num from alembic_version")
        self._report.add(f"Alembic: origen {source_version}, destino {target_version}")
        if self._apply and source_version != target_version:
            raise CopyAborted("Migrate the target to the same Alembic revision before applying")

        users = {r["email"]: dict(r) for r in await self._source.fetch("select * from users where email = any($1::text[])", emails)}
        missing = set(emails) - users.keys()
        if missing:
            raise CopyAborted(f"Not in the source: {sorted(missing)}")
        source_ids = {u["id"] for u in users.values()}

        user_map: dict[int, int] = {}
        for email in emails:
            source_user = users[email]
            target_user = await self._target.fetchrow("select * from users where email = $1", email)
            decision = decide_account(source_user, dict(target_user) if target_user else None, update, replace)
            user_map[source_user["id"]] = await self._copy_user(source_user, dict(target_user) if target_user else None, decision)

        profile_map = await self._copy_profiles(source_ids, user_map)
        analysis_map = await self._copy_analyses(profile_map)
        await self._copy_conversations(source_ids, user_map, analysis_map)
        await self._copy_teams(source_ids, user_map, profile_map)
        await self._check_no_foreign_urls()

    async def _copy_user(self, source_user: dict, target_user: dict | None, decision: AccountDecision) -> int:
        email = source_user["email"]
        if decision.action == "keep":
            self._report.add(f"\nCuenta {email}: ya copiada (id {decision.target_id}), no cambio nada")
            return decision.target_id
        if decision.action == "replace":
            await self._delete_user(target_user)
        values = dict(source_user)
        values["avatar_url"] = self._file(values["avatar_url"])
        if decision.action == "update":
            self._report.add(f"\nCuenta {email}: actualizo la fila del destino (id {decision.target_id})")
            self._describe_changes(target_user, values)
            await self._update("users", decision.target_id, values)
            return decision.target_id
        new_id = await self._insert("users", values)
        self._report.add(f"\nCuenta {email}: la copio como nueva (id destino {new_id if self._apply else 'nuevo'}): "
                         f"{values['role']}, activa={values['is_active']}, verificada={values['is_verified']}, mismo hash de contraseña, "
                         f"foto={'sí' if values['avatar_url'] else 'no'}")
        return new_id

    def _describe_changes(self, before: dict, after: dict) -> None:
        for column in SHOWN_ACCOUNT_COLUMNS:
            self._report.add(f"  {column}: {before.get(column)!r} -> {after.get(column)!r}")
        for column in sorted(SECRET_COLUMNS):
            same = before.get(column) == after.get(column)
            self._report.add(f"  {column}: {'igual' if same else 'cambia (copio el de origen)'}")

    async def _delete_user(self, user: dict) -> None:
        user_id = user["id"]
        profiles = await self._target.fetch("select id, user_id, full_name from athlete_profiles where user_id = $1 or coach_id = $1", user_id)
        for profile in profiles:
            # Un perfil gestionado que tiene su propia cuenta es de otra persona: no lo borro
            if profile["user_id"] not in (None, user_id):
                raise CopyAborted(f"Profile {profile['id']} belongs to another account (user {profile['user_id']})")
        profile_ids = [p["id"] for p in profiles]
        analyses = await self._target.fetch("select id, video_reference from jump_analyses where athlete_id = any($1::int[])", profile_ids)
        analysis_ids = [a["id"] for a in analyses]
        conversations = [r[0] for r in await self._target.fetch("select id from chat_conversations where jump_analysis_id = any($1::int[]) or user_id = $2", analysis_ids, user_id)]
        teams = [r[0] for r in await self._target.fetch("select id from teams where owner_id = $1", user_id)]
        counts = {
            "chat_messages": await self._target.fetchval("select count(*) from chat_messages where conversation_id = any($1::int[])", conversations),
            "chat_conversations": len(conversations),
            "joint_angle_measurements": await self._target.fetchval("select count(*) from joint_angle_measurements where jump_analysis_id = any($1::int[])", analysis_ids),
            "team_members": await self._target.fetchval("select count(*) from team_members where team_id = any($1::int[]) or athlete_id = any($2::int[])", teams, profile_ids),
            "jump_analyses": len(analysis_ids),
            "teams": len(teams),
            "athlete_profiles": len(profile_ids),
            "refresh_tokens": await self._target.fetchval("select count(*) from refresh_tokens where user_id = $1", user_id),
            "users": 1,
        }
        self._report.add(f"\nBorro del destino la cuenta {user['email']} (id {user_id}, {user['role']}, creada {user['created_at']:%Y-%m-%d}):")
        for profile in profiles:
            self._report.add(f"  perfil {profile['id']} {profile['full_name']!r}")
        for analysis in analyses:
            self._report.add(f"  análisis {analysis['id']}: {analysis['video_reference']} (el objeto no se borra del bucket)")
        self._report.add("  filas: " + ", ".join(f"{table} {n}" for table, n in counts.items()))
        if not self._apply:
            return
        # Borro en orden explícito, sin depender de los ON DELETE de cada llave
        await self._target.execute("delete from chat_messages where conversation_id = any($1::int[])", conversations)
        await self._target.execute("delete from chat_conversations where id = any($1::int[])", conversations)
        await self._target.execute("delete from joint_angle_measurements where jump_analysis_id = any($1::int[])", analysis_ids)
        await self._target.execute("delete from team_members where team_id = any($1::int[]) or athlete_id = any($2::int[])", teams, profile_ids)
        await self._target.execute("delete from jump_analyses where id = any($1::int[])", analysis_ids)
        await self._target.execute("delete from teams where id = any($1::int[])", teams)
        await self._target.execute("delete from athlete_profiles where id = any($1::int[])", profile_ids)
        await self._target.execute("delete from refresh_tokens where user_id = $1", user_id)
        await self._target.execute("delete from users where id = $1", user_id)

    async def _copy_profiles(self, source_ids: set[int], user_map: dict[int, int]) -> dict[int, int]:
        profile_map: dict[int, int] = {}
        rows = await self._source.fetch("select * from athlete_profiles where user_id = any($1::int[]) or coach_id = any($1::int[]) order by id", list(source_ids))
        for row in rows:
            values = dict(row)
            for column in ("user_id", "coach_id"):
                if values[column] is not None:
                    if values[column] not in user_map:
                        raise CopyAborted(f"Profile {row['id']} points to user {values[column]}, which is not being copied")
                    values[column] = user_map[values[column]]
            if values["user_id"] is not None:
                existing = await self._target.fetchval("select id from athlete_profiles where user_id = $1", values["user_id"]) if not self._is_fake(values["user_id"]) else None
            else:
                existing = await self._target.fetchval(
                    "select id from athlete_profiles where coach_id = $1 and full_name = $2 and birth_date is not distinct from $3",
                    values["coach_id"], values["full_name"], values["birth_date"],
                ) if not self._is_fake(values["coach_id"]) else None
            label = f"perfil {row['id']} ({'propio' if row['user_id'] else 'gestionado'} {row['full_name']!r})"
            if existing:
                self._report.add(f"{label}: ya existe en el destino (id {existing})")
                profile_map[row["id"]] = existing
                continue
            values["avatar_url"] = self._file(values["avatar_url"])
            profile_map[row["id"]] = await self._insert("athlete_profiles", values)
            self._report.add(f"{label}: lo copio, foto={'sí' if values['avatar_url'] else 'no'}")
        return profile_map

    async def _copy_analyses(self, profile_map: dict[int, int]) -> dict[int, int]:
        analysis_map: dict[int, int] = {}
        rows = await self._source.fetch("select * from jump_analyses where athlete_id = any($1::int[]) order by id", list(profile_map))
        for row in rows:
            values = dict(row)
            values["athlete_id"] = profile_map[row["athlete_id"]]
            # En seco el perfil nuevo aún no tiene id: lo marco en la ruta
            folder = "<id nuevo>" if self._is_fake(values["athlete_id"]) else values["athlete_id"]
            values["video_reference"] = self._file(values["video_reference"], athlete_id=folder)
            existing = await self._target.fetchval("select id from jump_analyses where video_reference = $1", values["video_reference"])
            if existing:
                analysis_map[row["id"]] = existing
                self._report.add(f"análisis {row['id']}: ya existe en el destino (id {existing})")
                continue
            new_id = await self._insert("jump_analyses", values)
            analysis_map[row["id"]] = new_id
            measurements = await self._source.fetch("select * from joint_angle_measurements where jump_analysis_id = $1 order by id", row["id"])
            for measurement in measurements:
                await self._insert("joint_angle_measurements", {**dict(measurement), "jump_analysis_id": new_id})
            self._report.add(f"análisis {row['id']} ({row['movement_type']}, {row['recorded_at']:%Y-%m-%d}): lo copio con {len(measurements)} mediciones")
        return analysis_map

    async def _copy_conversations(self, source_ids: set[int], user_map: dict[int, int], analysis_map: dict[int, int]) -> None:
        rows = await self._source.fetch("select * from chat_conversations where jump_analysis_id = any($1::int[]) or user_id = any($2::int[]) order by id", list(analysis_map), list(source_ids))
        for row in rows:
            if row["user_id"] not in user_map or row["jump_analysis_id"] not in analysis_map:
                self._report.add(f"chat {row['id']}: no lo copio (es de una cuenta o un análisis que no pasa)")
                continue
            user_id, analysis_id = user_map[row["user_id"]], analysis_map[row["jump_analysis_id"]]
            existing = None if self._is_fake(user_id) or self._is_fake(analysis_id) else await self._target.fetchval(
                "select id from chat_conversations where jump_analysis_id = $1 and user_id = $2", analysis_id, user_id)
            if existing:
                self._report.add(f"chat {row['id']}: ya existe en el destino (id {existing})")
                continue
            new_id = await self._insert("chat_conversations", {**dict(row), "user_id": user_id, "jump_analysis_id": analysis_id})
            messages = await self._source.fetch("select * from chat_messages where conversation_id = $1 order by id", row["id"])
            for message in messages:
                await self._insert("chat_messages", {**dict(message), "conversation_id": new_id})
            self._report.add(f"chat {row['id']}: lo copio con {len(messages)} mensajes")

    async def _copy_teams(self, source_ids: set[int], user_map: dict[int, int], profile_map: dict[int, int]) -> None:
        rows = await self._source.fetch("select * from teams where owner_id = any($1::int[]) order by id", list(source_ids))
        for row in rows:
            owner_id = user_map[row["owner_id"]]
            existing = None if self._is_fake(owner_id) else await self._target.fetchval("select id from teams where owner_id = $1 and name = $2", owner_id, row["name"])
            values = {**dict(row), "owner_id": owner_id}
            if "logo_url" in values:
                values["logo_url"] = self._file(values["logo_url"])
            team_id = existing or await self._insert("teams", values)
            members = await self._source.fetch("select athlete_id from team_members where team_id = $1", row["id"])
            copied = [profile_map[m["athlete_id"]] for m in members if m["athlete_id"] in profile_map]
            if self._apply:
                for athlete_id in copied:
                    await self._target.execute("insert into team_members (team_id, athlete_id) values ($1, $2) on conflict do nothing", team_id, athlete_id)
            skipped = len(members) - len(copied)
            self._report.add(f"equipo {row['id']} {row['name']!r}: {'ya existe' if existing else 'lo copio'}, {len(copied)} miembros" + (f", {skipped} que no pasan" if skipped else ""))

    async def _check_no_foreign_urls(self) -> None:
        prefixes = self._buckets.target_prefixes()
        foreign = []
        target_columns = {t: await self._columns(t) for t, _ in FILE_COLUMNS}
        for table, column in FILE_COLUMNS:
            if column not in target_columns[table]:
                continue
            rows = await self._target.fetch(f"select id, {column} from {table} where {column} is not null")
            foreign += [f"{table}.{column} id {r['id']}: {r[column]}" for r in rows if not r[column].startswith(prefixes)]
        if self._apply:
            if foreign:
                raise CopyAborted("URLs outside the target buckets: " + "; ".join(foreign))
            self._report.add("\nNinguna URL del destino apunta fuera de los buckets de destino")
        else:
            # En seco las filas borradas siguen ahí: las muestro para revisarlas a mano
            self._report.add("\nURLs del destino que hoy apuntan fuera de los buckets de destino (deben ser solo las que se borran):")
            for line in foreign or ["  ninguna"]:
                self._report.add(f"  {line}")

    def _file(self, url: str | None, athlete_id: int | str | None = None) -> str | None:
        new_url, copy = self._buckets.rewrite(url, athlete_id)
        if copy:
            self._report.copies.append(copy)
        return new_url

    async def _columns(self, table: str) -> list[str]:
        if table not in self._target_columns:
            self._target_columns[table] = await columns_of(self._target, table)
        return self._target_columns[table]

    async def _insert(self, table: str, values: dict) -> int:
        columns = [c for c in await self._columns(table) if c != "id" and c in values]
        lost = sorted(set(values) - set(columns) - {"id"})
        if lost:
            if self._apply:
                raise CopyAborted(f"{table} in the target lacks columns {lost}")
            if table not in self._noted_missing:
                self._noted_missing.add(table)
                self._report.add(f"  (en seco: {table} del destino aún no tiene {lost}; las agrega la migración)")
        if not self._apply:
            self._fake_id -= 1
            return self._fake_id
        placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        return await self._target.fetchval(
            f"insert into {table} ({', '.join(columns)}) values ({placeholders}) returning id", *(values[c] for c in columns)
        )

    async def _update(self, table: str, row_id: int, values: dict) -> None:
        if not self._apply:
            return
        columns = [c for c in await self._columns(table) if c not in ("id", "email") and c in values]
        assignments = ", ".join(f"{c} = ${i}" for i, c in enumerate(columns, start=2))
        await self._target.execute(f"update {table} set {assignments} where id = $1", row_id, *(values[c] for c in columns))

    @staticmethod
    def _is_fake(row_id: int) -> bool:
        return row_id < 0


def copy_objects(copies: list[tuple[str, str, str, str]], storage: StorageSettings, apply: bool) -> None:
    client = boto3.client(
        "s3", endpoint_url=storage.AWS_ENDPOINT_URL_S3, region_name=storage.AWS_REGION,
        aws_access_key_id=storage.AWS_ACCESS_KEY_ID, aws_secret_access_key=storage.AWS_SECRET_ACCESS_KEY.get_secret_value(),
        config=Config(s3={"addressing_style": "path"}, connect_timeout=10, read_timeout=60, retries={"max_attempts": 3}),
    )
    print(f"\nArchivos: {len(copies)}")
    for source_bucket, source_key, target_bucket, target_key in copies:
        size = client.head_object(Bucket=source_bucket, Key=source_key)["ContentLength"]
        try:
            # Si ya está con el mismo tamaño, es de una corrida anterior
            if client.head_object(Bucket=target_bucket, Key=target_key)["ContentLength"] == size:
                print(f"  ya está {target_bucket}/{target_key}")
                continue
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        print(f"  {source_bucket}/{source_key} -> {target_bucket}/{target_key} ({size / 1e6:.1f} MB)")
        if apply:
            client.copy_object(Bucket=target_bucket, Key=target_key, CopySource={"Bucket": source_bucket, "Key": source_key})
            if client.head_object(Bucket=target_bucket, Key=target_key)["ContentLength"] != size:
                raise CopyAborted(f"Size mismatch after copying {target_key}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--email", dest="emails", action="append", required=True)
    parser.add_argument("--update-existing", action="append", default=[])
    parser.add_argument("--replace-existing", action="append", default=[])
    parser.add_argument("--source-images-bucket", default="kinesiapp-dev-images")
    parser.add_argument("--source-videos-bucket", default="kinesiapp-dev-videos")
    parser.add_argument("--target-images-bucket", default="kinesiapp-prod-images")
    parser.add_argument("--target-videos-bucket", default="kinesiapp-prod-videos")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if set(args.update_existing) & set(args.replace_existing):
        parser.error("an email cannot be both updated and replaced")

    database, storage = DatabaseSettings(), StorageSettings()
    if not (storage.AWS_ENDPOINT_URL_S3 and storage.AWS_ACCESS_KEY_ID and storage.AWS_SECRET_ACCESS_KEY):
        sys.exit("Configure the AWS_* storage variables in .env")
    buckets = Buckets(storage.AWS_ENDPOINT_URL_S3, args.source_images_bucket, args.source_videos_bucket, args.target_images_bucket, args.target_videos_bucket)
    print(f"{'APLICO' if args.apply else 'EN SECO'}: {database.POSTGRES_HOST} -> {args.target_host}\n")

    source, target = await connect(database, database.POSTGRES_HOST), await connect(database, args.target_host)
    report = Report()
    try:
        async with source.transaction(readonly=True):
            transaction = target.transaction(readonly=not args.apply)
            await transaction.start()
            try:
                await AccountCopier(source, target, buckets, args.apply, report).run(args.emails, set(args.update_existing), set(args.replace_existing))
                # Copio los archivos antes de confirmar: si uno falla, la base queda como estaba
                copy_objects(report.copies, storage, args.apply)
            except BaseException:
                await transaction.rollback()
                raise
            if args.apply:
                await transaction.commit()
                print("\nConfirmado.")
            else:
                await transaction.rollback()
                print("\nEn seco: no escribí nada.")
    except CopyAborted as error:
        sys.exit(f"\nABORTADO, sin cambios en la base: {error}")
    finally:
        await source.close()
        await target.close()


if __name__ == "__main__":
    asyncio.run(main())
