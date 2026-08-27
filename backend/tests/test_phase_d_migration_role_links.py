"""P0：0015/0016 的 permission/role link 幂等与降级清理静态守卫。

根因：migration/postgres CI 的 downgrade 0004 -> upgrade head roundtrip 中，0015 无条件重复插入
role_permissions 违反主键。守卫断言：
- upgrade 的 role link INSERT 使用 ON CONFLICT (role_id, permission_id) DO NOTHING（幂等）；
- downgrade 显式删除本 revision 引入的 role link 与 permission 行。
行为级证据由一次性 SQLite/PostgreSQL roundtrip 脚本补充（CI 的 migration/postgres 为权威）。
"""

from pathlib import Path


MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"


def test_0015_role_links_are_idempotent_and_cleaned_on_downgrade() -> None:
    source = (MIGRATIONS_DIR / "20260811_0015_phase_d_project_scope.py").read_text(
        encoding="utf-8"
    )
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in source, (
        "0015 upgrade 的 role link INSERT 必须幂等（ON CONFLICT DO NOTHING）"
    )
    assert "DELETE FROM role_permissions WHERE permission_id IN" in source, (
        "0015 downgrade 必须删除本 revision 引入的 role link"
    )
    assert "DELETE FROM permissions WHERE code IN" in source, (
        "0015 downgrade 必须清理本 revision 引入的 permission 行"
    )
    assert "('projects:read', 'projects:write', 'projects:manage')" in source


def test_0016_role_links_are_idempotent_and_cleaned_on_downgrade() -> None:
    source = (MIGRATIONS_DIR / "20260811_0016_phase_d_skill_grants.py").read_text(
        encoding="utf-8"
    )
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in source, (
        "0016 upgrade 的 role link INSERT 必须幂等（ON CONFLICT DO NOTHING）"
    )
    assert "DELETE FROM role_permissions WHERE permission_id IN" in source, (
        "0016 downgrade 必须删除本 revision 引入的 role link"
    )
    assert "DELETE FROM permissions WHERE code IN" in source, (
        "0016 downgrade 必须清理本 revision 引入的 permission 行"
    )
    assert "('skills:share', 'skills:govern')" in source
