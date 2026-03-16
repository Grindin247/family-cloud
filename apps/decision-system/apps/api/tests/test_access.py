import pytest
from fastapi import HTTPException

from app.models.entities import Family, FamilyMember, RoleEnum
from app.services.access import require_family_admin


def test_require_family_admin_allows_editor_when_family_has_no_admin(db_session):
    family = Family(name="No Admin Family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="editor@example.com",
            display_name="Editor",
            role=RoleEnum.editor,
        )
    )
    db_session.commit()

    member = require_family_admin(db_session, family.id, "editor@example.com")
    assert member.role == RoleEnum.editor


def test_require_family_admin_rejects_editor_when_family_has_admin(db_session):
    family = Family(name="Admin Family")
    db_session.add(family)
    db_session.flush()
    db_session.add_all(
        [
            FamilyMember(
                family_id=family.id,
                email="admin@example.com",
                display_name="Admin",
                role=RoleEnum.admin,
            ),
            FamilyMember(
                family_id=family.id,
                email="editor@example.com",
                display_name="Editor",
                role=RoleEnum.editor,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        require_family_admin(db_session, family.id, "editor@example.com")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "admin role required"
