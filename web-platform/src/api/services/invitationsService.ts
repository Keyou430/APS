import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type InvitationListQuery = Record<string, QueryValue>;
export type InvitationCreate = Record<string, unknown>;
export type InvitationRegenerate = Record<string, unknown>;
export type InvitationAccept = Record<string, unknown>;
export type InvitationResponse = Record<string, unknown>;
export type InvitationCreatedResponse = Record<string, unknown>;
export type InvitationAcceptResponse = Record<string, unknown>;
export type InvitationListResponse = Record<string, unknown>;
export type GuestMembershipResponse = Record<string, unknown>;

export type InvitationsService = {
  acceptInvitation(
    request: InvitationAccept,
  ): Promise<InvitationAcceptResponse>;
  createInvitation(
    request: InvitationCreate,
  ): Promise<InvitationCreatedResponse>;
  listInvitations(
    query?: InvitationListQuery,
  ): Promise<InvitationListResponse>;
  regenerateInvitation(
    invitationId: number,
    request: InvitationRegenerate,
  ): Promise<InvitationCreatedResponse>;
  revokeGuestMembership(
    membershipId: number,
  ): Promise<GuestMembershipResponse>;
  revokeInvitation(invitationId: number): Promise<InvitationResponse>;
};

export function createInvitationsService(
  client: ApiClient,
): InvitationsService {
  return {
    acceptInvitation(request) {
      return client.request<InvitationAcceptResponse>("/invitations/accept", {
        method: "POST",
        body: request,
      });
    },
    createInvitation(request) {
      return client.request<InvitationCreatedResponse>("/invitations", {
        method: "POST",
        body: request,
      });
    },
    listInvitations(query) {
      return client.request<InvitationListResponse>(
        appendQuery("/invitations", query),
      );
    },
    regenerateInvitation(invitationId, request) {
      return client.request<InvitationCreatedResponse>(
        `/invitations/${invitationId}/regenerate`,
        {
          method: "POST",
          body: request,
        },
      );
    },
    revokeGuestMembership(membershipId) {
      return client.request<GuestMembershipResponse>(
        `/invitations/guest-memberships/${membershipId}/revoke`,
        { method: "POST" },
      );
    },
    revokeInvitation(invitationId) {
      return client.request<InvitationResponse>(
        `/invitations/${invitationId}/revoke`,
        { method: "POST" },
      );
    },
  };
}
