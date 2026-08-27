import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  OrganizationService,
  OrganizationStructureResponse,
} from "../api/services/organizationService";
import {
  asObject,
  errorStatus,
  readArray,
  readNumber,
  readString,
  type PageCache,
} from "./pageUtils";

type OrganizationPageProps = {
  cache: PageCache;
  organizationId: number | null;
  service: OrganizationService;
};

type PageStatus = "loading" | "empty" | "error" | "forbidden" | "conflict" | "success";

type UnitRow = {
  code: string;
  id: number;
  isActive: boolean;
  name: string;
  parentId: number | null;
};

type PositionRow = {
  id: number;
  isActive: boolean;
  level: string;
  title: string;
  unitId: number;
};

type PersonRow = {
  email: string;
  membershipId: number;
  memberType: string;
  role: string;
  username: string;
};

type OrganizationViewModel = {
  organizationId: number;
  people: PersonRow[];
  placementsCount: number;
  positions: PositionRow[];
  revision: number;
  units: UnitRow[];
};

function mapUnit(value: unknown, index: number): UnitRow {
  const item = asObject(value);
  const parentId = readNumber(item.parent_id, -1);
  return {
    code: readString(item.code, `unit-${index + 1}`),
    id: readNumber(item.id, index + 1),
    isActive: item.is_active !== false,
    name: readString(item.name, `组织单元 ${index + 1}`),
    parentId: parentId > 0 ? parentId : null,
  };
}

function mapPosition(value: unknown, index: number): PositionRow {
  const item = asObject(value);
  return {
    id: readNumber(item.id, index + 1),
    isActive: item.is_active !== false,
    level: readString(item.level, "未分级"),
    title: readString(item.title, readString(item.name, `职位 ${index + 1}`)),
    unitId: readNumber(item.unit_id),
  };
}

function mapPerson(value: unknown, index: number): PersonRow {
  const item = asObject(value);
  return {
    email: readString(item.email),
    membershipId: readNumber(item.membership_id, index + 1),
    memberType: readString(item.member_type, "internal"),
    role: readString(item.role, "user"),
    username: readString(item.username, `成员 ${index + 1}`),
  };
}

function mapOrganization(
  response: OrganizationStructureResponse,
): OrganizationViewModel {
  return {
    organizationId: readNumber(response.organization_id),
    people: readArray(response.people).map(mapPerson),
    placementsCount: readArray(response.placements).length,
    positions: readArray(response.positions).map(mapPosition),
    revision: readNumber(response.revision),
    units: readArray(response.units).map(mapUnit),
  };
}

function messageForError(error: unknown) {
  const status = errorStatus(error);
  if (status === 403) return "没有组织架构访问权限";
  if (status === 409) return "组织架构版本已变化，请刷新后再试";
  if (status === 404) return "组织资源不存在或已被隐藏";
  return "组织架构加载失败";
}

export function OrganizationPage({
  cache,
  organizationId,
  service,
}: OrganizationPageProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<PageStatus>(
    organizationId === null ? "forbidden" : "loading",
  );
  const [viewModel, setViewModel] = useState<OrganizationViewModel | null>(null);
  const cacheKey = useMemo(() => ["organization", "structure"], []);

  const loadStructure = useCallback(async () => {
    if (organizationId === null) {
      setStatus("forbidden");
      setViewModel(null);
      setErrorMessage("没有组织架构访问权限");
      return;
    }

    setErrorMessage(null);
    setStatus("loading");
    try {
      const cached = cache.get<OrganizationViewModel>(organizationId, cacheKey);
      const next = cached ?? mapOrganization(await service.getStructure());
      if (!cached) cache.set(organizationId, cacheKey, next);
      setViewModel(next);
      setStatus(
        next.units.length || next.positions.length || next.people.length
          ? "success"
          : "empty",
      );
    } catch (error) {
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
      setViewModel(null);
    }
  }, [cache, cacheKey, organizationId, service]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadStructure();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadStructure]);

  async function refreshStructure() {
    if (organizationId === null) return;
    cache.invalidateOrganization(organizationId);
    await loadStructure();
  }

  async function deletePosition(position: PositionRow) {
    if (!viewModel || organizationId === null || status === "forbidden") return;
    setErrorMessage(null);
    try {
      await service.deletePosition(position.id, {
        expected_revision: viewModel.revision,
      });
      cache.invalidateOrganization(organizationId);
      setViewModel({
        ...viewModel,
        positions: viewModel.positions.filter((item) => item.id !== position.id),
      });
      setStatus("success");
    } catch (error) {
      setStatus(errorStatus(error) === 409 ? "conflict" : errorStatus(error) === 403 ? "forbidden" : "error");
      setErrorMessage(messageForError(error));
    }
  }

  const canManage =
    organizationId !== null &&
    viewModel !== null &&
    status !== "forbidden" &&
    status !== "conflict";

  return (
    <main aria-labelledby="organization-title" className="page-view organization-page">
      <header className="page-header">
        <div>
          <h1 id="organization-title">组织架构</h1>
          <p>管理当前组织的部门、职位和成员归属。</p>
        </div>
        <button
          disabled={organizationId === null || status === "forbidden"}
          onClick={() => void refreshStructure()}
          type="button"
        >
          刷新组织架构
        </button>
      </header>

      {errorMessage ? (
        <p className="error-message" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {status === "loading" ? <p>正在加载组织架构</p> : null}
      {status === "empty" ? <p>组织架构暂无数据</p> : null}

      {viewModel ? (
        <>
          <section aria-label="组织摘要">
            <p>结构版本 {viewModel.revision}</p>
            <dl>
              <div>
                <dt>部门</dt>
                <dd>{viewModel.units.length}</dd>
              </div>
              <div>
                <dt>职位</dt>
                <dd>{viewModel.positions.length}</dd>
              </div>
              <div>
                <dt>成员</dt>
                <dd>{viewModel.people.length}</dd>
              </div>
              <div>
                <dt>任职记录</dt>
                <dd>{viewModel.placementsCount}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="组织单元">
            <h2>部门</h2>
            {viewModel.units.length ? (
              <ul>
                {viewModel.units.map((unit) => (
                  <li key={unit.id}>
                    <strong>{unit.name}</strong>
                    <span>{unit.code}</span>
                    <span>{unit.isActive ? "启用" : "停用"}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无部门</p>
            )}
          </section>

          <section aria-label="组织职位">
            <h2>职位</h2>
            {viewModel.positions.length ? (
              <ul>
                {viewModel.positions.map((position) => (
                  <li key={position.id}>
                    <strong>{position.title}</strong>
                    <span>{position.level}</span>
                    <span>{position.isActive ? "启用" : "停用"}</span>
                    <button
                      aria-label={`删除 ${position.title} 职位`}
                      disabled={!canManage}
                      onClick={() => void deletePosition(position)}
                      type="button"
                    >
                      删除
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无职位</p>
            )}
          </section>

          <section aria-label="组织成员">
            <h2>成员</h2>
            {viewModel.people.length ? (
              <ul>
                {viewModel.people.map((person) => (
                  <li key={person.membershipId}>
                    <strong>{person.username}</strong>
                    <span>{person.email}</span>
                    <span>{person.role}</span>
                    <span>{person.memberType}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无成员</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
