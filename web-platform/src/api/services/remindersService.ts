import type { ApiClient } from "../client";
import { appendQuery, type QueryValue } from "./serviceUtils";

export type ReminderListQuery = Record<string, QueryValue>;
export type ReminderUpcomingQuery = Record<string, QueryValue>;
export type ReminderCreate = Record<string, unknown>;
export type ReminderUpdate = Record<string, unknown>;
export type ReminderResponse = Record<string, unknown>;
export type ReminderListResponse = Record<string, unknown>;

export type RemindersService = {
  completeReminder(reminderId: number): Promise<ReminderResponse>;
  createReminder(request: ReminderCreate): Promise<ReminderResponse>;
  deleteReminder(reminderId: number): Promise<void>;
  listReminders(query?: ReminderListQuery): Promise<ReminderListResponse>;
  listUpcoming(
    query?: ReminderUpcomingQuery,
  ): Promise<ReminderListResponse>;
  updateReminder(
    reminderId: number,
    request: ReminderUpdate,
  ): Promise<ReminderResponse>;
};

export function createRemindersService(client: ApiClient): RemindersService {
  return {
    completeReminder(reminderId) {
      return client.request<ReminderResponse>(
        `/reminders/${reminderId}/complete`,
        { method: "POST" },
      );
    },
    createReminder(request) {
      return client.request<ReminderResponse>("/reminders", {
        method: "POST",
        body: request,
      });
    },
    deleteReminder(reminderId) {
      return client.request<void>(`/reminders/${reminderId}`, {
        method: "DELETE",
      });
    },
    listReminders(query) {
      return client.request<ReminderListResponse>(
        appendQuery("/reminders", query),
      );
    },
    listUpcoming(query) {
      return client.request<ReminderListResponse>(
        appendQuery("/reminders/upcoming", query),
      );
    },
    updateReminder(reminderId, request) {
      return client.request<ReminderResponse>(`/reminders/${reminderId}`, {
        method: "PUT",
        body: request,
      });
    },
  };
}
