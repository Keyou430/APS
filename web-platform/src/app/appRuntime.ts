import { createAuthRuntime, type AuthRuntime } from "../features/auth/authRuntime";
import {
  createContractAuthBridge,
  type ContractAuthBridge,
} from "../auth/contractAuthBridge";
import {
  createChatService,
  type ChatService,
} from "../api/services/chatService";
import {
  createChatStreamService,
  type ChatStreamService,
} from "../api/services/chatStream";
import {
  createAuditService,
  type AuditService,
} from "../api/services/auditService";
import {
  createEnterpriseService,
  type EnterpriseService,
} from "../api/services/enterpriseService";
import {
  createDashboardService,
  type DashboardService,
} from "../api/services/dashboardService";
import {
  createHermesService,
  type HermesService,
} from "../api/services/hermesService";
import {
  createInvitationsService,
  type InvitationsService,
} from "../api/services/invitationsService";
import {
  createKnowledgeService,
  type KnowledgeService,
} from "../api/services/knowledgeService";
import {
  createExperienceService,
  type ExperienceService,
} from "../api/services/experienceService";
import {
  createPipelineService,
  type PipelineService,
} from "../api/services/pipelineService";
import {
  createMemoryService,
  type MemoryService,
} from "../api/services/memoryService";
import {
  createOrganizationService,
  type OrganizationService,
} from "../api/services/organizationService";
import {
  createRemindersService,
  type RemindersService,
} from "../api/services/remindersService";
import {
  createSkillsService,
  type SkillsService,
} from "../api/services/skillsService";
import {
  createUsersService,
  type UsersService,
} from "../api/services/usersService";
import {
  createWorkItemsService,
  type WorkItemsService,
} from "../api/services/workItemsService";
import { renderSafeAssistantMarkdown } from "../security/safeMarkdown";
import { createUiStore, type UiStore } from "./uiStore";

export type AppRuntimeOptions = {
  auth?: Parameters<typeof createAuthRuntime>[0];
  ui?: Parameters<typeof createUiStore>[0];
};

export type AppRuntime = {
  auth: AuthRuntime;
  services: {
    chat: ChatService;
    chatStream: ChatStreamService;
    audit: AuditService;
    dashboard: DashboardService;
    enterprise: EnterpriseService;
    hermes: HermesService;
    invitations: InvitationsService;
    knowledge: KnowledgeService;
    experience: ExperienceService;
    memory: MemoryService;
    organization: OrganizationService;
    pipeline: PipelineService;
    reminders: RemindersService;
    skills: SkillsService;
    users: UsersService;
    workItems: WorkItemsService;
  };
  security: {
    renderAssistantMessage: (content: string) => string;
  };
  ui: UiStore;
};

export type AppRuntimeGlobal = {
  __agentRuntime?: AppRuntime;
  __contractAuth?: ContractAuthBridge;
};

declare global {
  interface Window {
    __agentRuntime?: AppRuntime;
    __contractAuth?: ContractAuthBridge;
  }
}

export function createAppRuntime(options: AppRuntimeOptions = {}): AppRuntime {
  const auth = createAuthRuntime(options.auth);
  return {
    auth,
    services: {
      chat: createChatService(auth.client),
      chatStream: createChatStreamService({
        getAccessToken: () =>
          auth.store.getState().session?.token.access_token ?? null,
        refresh: () => auth.refreshSession(),
        clearSession: () => {
          void auth.store.logout();
          // Mirror the client-side bridge so the legacy layer also drops its
          // in-memory token when streaming auth expires.
          if (
            typeof window !== "undefined" &&
            typeof window.dispatchEvent === "function"
          ) {
            window.dispatchEvent(
              new CustomEvent("agent-platform:session-cleared"),
            );
          }
        },
      }),
      audit: createAuditService(auth.client),
      dashboard: createDashboardService(auth.client),
      enterprise: createEnterpriseService(auth.client),
      hermes: createHermesService(auth.client),
      invitations: createInvitationsService(auth.client),
      knowledge: createKnowledgeService(auth.client),
      experience: createExperienceService(auth.client),
      memory: createMemoryService(auth.client),
      organization: createOrganizationService(auth.client),
      pipeline: createPipelineService(auth.client),
      reminders: createRemindersService(auth.client),
      skills: createSkillsService(auth.client),
      users: createUsersService(auth.client),
      workItems: createWorkItemsService(auth.client),
    },
    security: {
      renderAssistantMessage: renderSafeAssistantMarkdown,
    },
    ui: createUiStore(options.ui),
  };
}

export function installAppRuntime(
  target: AppRuntimeGlobal,
  options: AppRuntimeOptions = {},
): AppRuntime {
  const runtime = createAppRuntime(options);
  target.__agentRuntime = runtime;
  target.__contractAuth = createContractAuthBridge(runtime.auth);
  return runtime;
}
