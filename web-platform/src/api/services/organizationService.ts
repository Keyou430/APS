import type { ApiClient } from "../client";

export type RevisionRequest = {
  expected_revision: number;
};

export type OrganizationUnitCreate = Record<string, unknown> & RevisionRequest;
export type OrganizationUnitUpdate = Record<string, unknown> & RevisionRequest;
export type OrganizationPositionCreate = Record<string, unknown> &
  RevisionRequest;
export type OrganizationPositionUpdate = Record<string, unknown> &
  RevisionRequest;
export type OrganizationPlacementUpdate = Record<string, unknown> &
  RevisionRequest;
export type OrganizationPlacementBatch = Record<string, unknown> &
  RevisionRequest;
export type OrganizationStructureResponse = Record<string, unknown>;

export type OrganizationService = {
  createPosition(
    request: OrganizationPositionCreate,
  ): Promise<OrganizationStructureResponse>;
  createUnit(
    request: OrganizationUnitCreate,
  ): Promise<OrganizationStructureResponse>;
  deletePosition(
    positionId: number,
    request: RevisionRequest,
  ): Promise<void>;
  deleteUnit(unitId: number, request: RevisionRequest): Promise<void>;
  getStructure(): Promise<OrganizationStructureResponse>;
  updatePlacement(
    membershipId: number,
    request: OrganizationPlacementUpdate,
  ): Promise<OrganizationStructureResponse>;
  updatePlacementsBatch(
    request: OrganizationPlacementBatch,
  ): Promise<OrganizationStructureResponse>;
  updatePosition(
    positionId: number,
    request: OrganizationPositionUpdate,
  ): Promise<OrganizationStructureResponse>;
  updateUnit(
    unitId: number,
    request: OrganizationUnitUpdate,
  ): Promise<OrganizationStructureResponse>;
};

export function createOrganizationService(
  client: ApiClient,
): OrganizationService {
  return {
    createPosition(request) {
      return client.request<OrganizationStructureResponse>(
        "/organization/positions",
        {
          method: "POST",
          body: request,
        },
      );
    },
    createUnit(request) {
      return client.request<OrganizationStructureResponse>("/organization/units", {
        method: "POST",
        body: request,
      });
    },
    deletePosition(positionId, request) {
      return client.request<void>(`/organization/positions/${positionId}`, {
        method: "DELETE",
        body: request,
      });
    },
    deleteUnit(unitId, request) {
      return client.request<void>(`/organization/units/${unitId}`, {
        method: "DELETE",
        body: request,
      });
    },
    getStructure() {
      return client.request<OrganizationStructureResponse>(
        "/organization/structure",
      );
    },
    updatePlacement(membershipId, request) {
      return client.request<OrganizationStructureResponse>(
        `/organization/placements/${membershipId}`,
        {
          method: "PUT",
          body: request,
        },
      );
    },
    updatePlacementsBatch(request) {
      return client.request<OrganizationStructureResponse>(
        "/organization/placements/batch",
        {
          method: "POST",
          body: request,
        },
      );
    },
    updatePosition(positionId, request) {
      return client.request<OrganizationStructureResponse>(
        `/organization/positions/${positionId}`,
        {
          method: "PATCH",
          body: request,
        },
      );
    },
    updateUnit(unitId, request) {
      return client.request<OrganizationStructureResponse>(
        `/organization/units/${unitId}`,
        {
          method: "PATCH",
          body: request,
        },
      );
    },
  };
}
