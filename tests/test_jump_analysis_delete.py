"""Borrado de un análisis: permisos de lectura, cascada de mediciones y archivo en disco."""
from pathlib import Path

from app.core.config import settings
from app.models.jump_analysis import JointAngleMeasurement, JumpAnalysis
from tests.test_jump_analysis_rbac import _auth_headers, _create_athlete_profile


def _uploaded(client, register_and_verify, grant_consent, upload_jump, email):
    token = register_and_verify(email)
    athlete_id = _create_athlete_profile(client, token)
    grant_consent(token)
    r = upload_jump(token, athlete_id)
    assert r.status_code == 202, r.text
    return token, r.json()["id"]


def _video_path(db_session, analysis_id: int) -> Path:
    return Path(db_session.get(JumpAnalysis, analysis_id).video_reference)


def test_owner_deletes_analysis_with_its_measurements_and_video(
    client, register_and_verify, grant_consent, upload_jump, db_session
):
    token, analysis_id = _uploaded(client, register_and_verify, grant_consent, upload_jump, "del-owner@kinesiapp.com")
    video = _video_path(db_session, analysis_id)
    # El procesamiento en segundo plano ya guardó mediciones que deben irse con el análisis
    assert db_session.query(JointAngleMeasurement).filter_by(jump_analysis_id=analysis_id).count() > 0
    assert video.is_file()

    r = client.delete(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(token))
    assert r.status_code == 204, r.text

    assert client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(token)).status_code == 404
    db_session.expire_all()
    assert db_session.query(JointAngleMeasurement).filter_by(jump_analysis_id=analysis_id).count() == 0
    assert not video.exists()


def test_intruder_cannot_delete_and_nothing_is_removed(
    client, register_and_verify, grant_consent, upload_jump, db_session
):
    owner, analysis_id = _uploaded(client, register_and_verify, grant_consent, upload_jump, "del-owner2@kinesiapp.com")
    intruder = register_and_verify("del-intruder@kinesiapp.com")
    video = _video_path(db_session, analysis_id)

    r = client.delete(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(intruder))
    assert r.status_code == 403
    assert client.get(f"/api/v1/jump-analyses/{analysis_id}", headers=_auth_headers(owner)).status_code == 200
    assert video.is_file()


def test_deleting_a_missing_analysis_is_404(client, register_and_verify):
    token = register_and_verify("del-404@kinesiapp.com")
    assert client.delete("/api/v1/jump-analyses/99999", headers=_auth_headers(token)).status_code == 404


def test_storage_never_deletes_files_outside_the_video_directory(tmp_path):
    from app.services.jump_video_storage import JumpVideoStorage

    outside = tmp_path / "not-a-video.txt"
    outside.write_text("keep me")
    JumpVideoStorage(settings.VIDEO_UPLOAD_DIR, settings.MAX_VIDEO_UPLOAD_BYTES).delete(outside)
    assert outside.exists()
