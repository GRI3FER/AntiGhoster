import tempfile

import pytest

import app as alumni_app


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        monkeypatch.setattr(alumni_app, "DATABASE", f"{directory}\\test.sqlite3")
        alumni_app.app.config.update(TESTING=True, ENV="development")
        with alumni_app.app.app_context():
            alumni_app.init_db()
        with alumni_app.app.test_client() as test_client:
            yield test_client


def register_and_verify(client, email, role):
    response = client.post(
        "/api/register", json={"email": email, "password": "password123", "role": role}
    )
    body = response.get_json()
    assert response.status_code == 201
    verification = client.post(
        "/api/verify-email",
        json={"user_id": body["user_id"], "token": body["verification_token"]},
    )
    assert verification.status_code == 200
    return body["user_id"]


def login(client, email):
    response = client.post("/api/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200


def create_network(client, name, join_mode="open", password=None):
    response = client.post(
        "/api/networks", json={"name": name, "join_mode": join_mode, "password": password}
    )
    assert response.status_code == 201
    return response.get_json()["network_id"]


def test_student_requires_edu_and_verification(client):
    assert client.post(
        "/api/register",
        json={"email": "student@example.com", "password": "password123", "role": "student"},
    ).status_code == 400
    user_id = register_and_verify(client, "student@university.edu", "student")
    login(client, "student@university.edu")
    network_id = create_network(client, "Campus Club")
    assert client.post(f"/api/networks/{network_id}/join").get_json()["status"] == "active"
    assert user_id


def test_unverified_user_cannot_log_in_or_create_network(client):
    client.post(
        "/api/register",
        json={"email": "student@university.edu", "password": "password123", "role": "student"},
    )
    assert client.post(
        "/api/login",
        json={"email": "student@university.edu", "password": "password123"},
    ).status_code == 403


def test_alumni_requires_approval_even_for_open_network(client):
    register_and_verify(client, "manager@university.edu", "student")
    login(client, "manager@university.edu")
    network_id = create_network(client, "Alumni Club")
    register_and_verify(client, "alumnus@example.com", "alumni")
    login(client, "alumnus@example.com")
    response = client.post(
        f"/api/networks/{network_id}/join",
        json={"participation_years": "2010-2014", "supporting_information": "Roster"},
    )
    assert response.get_json()["status"] == "pending"
    assert client.get(f"/api/networks/{network_id}/members").status_code == 403
    assert client.get(f"/api/networks/{network_id}/application").status_code == 200


def test_alumni_requires_supporting_information(client):
    register_and_verify(client, "manager@university.edu", "student")
    login(client, "manager@university.edu")
    network_id = create_network(client, "Evidence Club")
    register_and_verify(client, "alumnus@example.com", "alumni")
    login(client, "alumnus@example.com")
    response = client.post(
        f"/api/networks/{network_id}/join",
        json={"participation_years": "2010-2014"},
    )
    assert response.status_code == 400


def test_manager_can_request_evidence_and_approve(client):
    register_and_verify(client, "manager@university.edu", "student")
    login(client, "manager@university.edu")
    network_id = create_network(client, "Evidence Club")
    register_and_verify(client, "alumnus@example.com", "alumni")
    login(client, "alumnus@example.com")
    client.post(
        f"/api/networks/{network_id}/join",
        json={
            "participation_years": "2010-2014",
            "supporting_information": "Graduation roster",
        },
    )
    login(client, "manager@university.edu")
    evidence = client.post(
        f"/api/networks/{network_id}/members/2/review",
        json={"decision": "request_evidence", "note": "Provide a roster link"},
    )
    assert evidence.get_json()["status"] == "evidence_requested"
    approved = client.post(
        f"/api/networks/{network_id}/members/2/review",
        json={"decision": "approve"},
    )
    assert approved.get_json()["status"] == "active"


def test_student_to_alumni_suspends_active_membership(client):
    register_and_verify(client, "student@university.edu", "student")
    login(client, "student@university.edu")
    network_id = create_network(client, "Transition Club")
    client.post(f"/api/networks/{network_id}/join")
    assert client.post("/api/me/role", json={"role": "alumni"}).get_json()["role"] == "alumni"
    assert client.get(f"/api/networks/{network_id}/members").status_code == 403
