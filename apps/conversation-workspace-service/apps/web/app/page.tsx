"use client";

import { FormEvent, KeyboardEvent, startTransition, useDeferredValue, useEffect, useRef, useState } from "react";
import {
  ActionProposal,
  api,
  AssistantMode,
  Attachment,
  buildRealtimeUrl,
  Conversation,
  ConversationKind,
  ConversationParticipant,
  Message,
  TopLevelAssistant,
  ViewerContextResponse,
  ViewerMeResponse,
} from "../lib/api";

const QUICK_ACTIONS = [
  { label: "Add tasks", prefix: "Add new tasks for the following:" },
  { label: "Capture note", prefix: "Save a note about the following:" },
  { label: "Make plan", prefix: "Create a plan for the following:" },
];

const SPACE_OPTIONS = [
  { value: "planning", label: "Planning" },
  { value: "notes", label: "Notes" },
  { value: "decisions", label: "Decisions" },
  { value: "education", label: "Education" },
];

const ASSISTANTS: Array<{ id: TopLevelAssistant; label: string }> = [
  { id: "caleb", label: "Caleb" },
  { id: "amelia", label: "Amelia" },
];

const DRAFT_STORAGE_KEY = "conversation-workspace-drafts-v1";

function formatDateTime(value?: string | null): string {
  if (!value) return "Now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatConversationKind(conversation: Conversation): string {
  if (conversation.kind === "assistant") return "Assistant";
  if (conversation.space_type !== "none") return "With Assistant";
  if (conversation.kind === "hybrid") return "With Assistant";
  return "Family";
}

function assistantParticipant(conversation: Conversation | null, assistantId: TopLevelAssistant): ConversationParticipant | undefined {
  if (!conversation) return undefined;
  return conversation.participants.find((participant) => participant.top_level_assistant === assistantId);
}

function conversationPreview(conversation: Conversation): string {
  return conversation.latest_message_preview || conversation.latest_summary || "No messages yet.";
}

function blockSummary(message: Message): string {
  const special = message.blocks.find((block) => block.block_type !== "markdown");
  if (!special) return message.body_text || "";
  if (special.block_type === "approval_card") {
    return String(special.data.summary || message.body_text || "Draft action");
  }
  if (special.block_type === "summary_card") {
    return String(special.text_content || message.body_text || "Shared summary");
  }
  if (special.block_type === "agent_activity") {
    return String(special.data.summary || message.body_text || "Agent activity");
  }
  return message.body_text || "";
}

function messageClass(message: Message, selected: boolean): string {
  const parts = ["message-card"];
  parts.push(`message-${message.sender_kind}`);
  if (selected) parts.push("is-selected");
  return parts.join(" ");
}

export default function Page() {
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const [me, setMe] = useState<ViewerMeResponse | null>(null);
  const [context, setContext] = useState<ViewerContextResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [composerText, setComposerText] = useState("");
  const [quickActionPrefix, setQuickActionPrefix] = useState<string | null>(null);
  const [invokeAssistant, setInvokeAssistant] = useState(false);
  const [selectedAssistantId, setSelectedAssistantId] = useState<TopLevelAssistant | "">("");
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([]);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [shareTargetConversationId, setShareTargetConversationId] = useState("");
  const [shareNote, setShareNote] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newConversationMode, setNewConversationMode] = useState<"closed" | "family" | "shared">("closed");
  const [newConversationTitle, setNewConversationTitle] = useState("");
  const [newConversationParticipantIds, setNewConversationParticipantIds] = useState<string[]>([]);
  const [newSharedSpaceType, setNewSharedSpaceType] = useState("planning");
  const [newSharedAssistants, setNewSharedAssistants] = useState<TopLevelAssistant[]>(["amelia"]);
  const [newSharedAssistantModes, setNewSharedAssistantModes] = useState<Record<TopLevelAssistant, AssistantMode>>({
    caleb: "passive",
    amelia: "active",
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          setDrafts(parsed as Record<string, string>);
        }
      }
    } catch {
      // Ignore malformed drafts and start fresh.
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(drafts));
  }, [drafts]);

  useEffect(() => {
    async function bootstrap() {
      try {
        setLoading(true);
        setErrorMessage("");
        const meResponse = await api.getMe();
        setMe(meResponse);
        const membership = meResponse.memberships[0];
        if (!membership) {
          throw new Error("No family memberships were found for this account.");
        }
        const nextFamilyId = membership.family_id;
        setFamilyId(nextFamilyId);
        const viewerContext = await api.getViewerContext(nextFamilyId);
        setContext(viewerContext);
        const listing = await api.listConversations(nextFamilyId);
        setConversations(listing.items);
        const firstConversationId = listing.items[0]?.conversation_id ?? null;
        setSelectedConversationId(firstConversationId);
        if (firstConversationId) {
          const detail = await api.getConversation(nextFamilyId, firstConversationId);
          setSelectedConversation(detail);
        }
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Could not load the chat workspace.");
      } finally {
        setLoading(false);
      }
    }

    void bootstrap();
  }, []);

  useEffect(() => {
    if (!selectedConversationId) return;
    const nextDraft = drafts[selectedConversationId] ?? "";
    setComposerText(nextDraft);
    setPendingAttachments([]);
    setSelectedMessageId(null);
    setShareNote("");
    setQuickActionPrefix(null);
    if (selectedConversation?.kind === "assistant") {
      setInvokeAssistant(true);
      const assistant = selectedConversation.participants.find((participant) => participant.top_level_assistant);
      setSelectedAssistantId((assistant?.top_level_assistant as TopLevelAssistant | undefined) ?? "");
    } else {
      setInvokeAssistant(false);
      setSelectedAssistantId("");
    }
  }, [drafts, selectedConversation, selectedConversationId]);

  useEffect(() => {
    if (!selectedConversation) return;
    const options = conversations.filter((conversation) => conversation.conversation_id !== selectedConversation.conversation_id);
    if (!options.length) {
      setShareTargetConversationId("");
      return;
    }
    if (!shareTargetConversationId || !options.some((item) => item.conversation_id === shareTargetConversationId)) {
      setShareTargetConversationId(options[0].conversation_id);
    }
  }, [conversations, selectedConversation, shareTargetConversationId]);

  useEffect(() => {
    if (!familyId || !selectedConversationId) return;
    const socket = new WebSocket(buildRealtimeUrl(familyId, selectedConversationId));

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        if (payload.type === "pong") return;
        if (payload.type === "typing") {
          setStatusMessage(`${String(payload.actor || "Someone")} is typing...`);
          return;
        }
        startTransition(() => {
          void refreshConversations(selectedConversationId);
        });
      } catch {
        // Ignore malformed websocket payloads.
      }
    };

    socket.onerror = () => {
      setStatusMessage("Realtime connection is reconnecting.");
    };

    return () => {
      socket.close();
    };
  }, [familyId, selectedConversationId]);

  useEffect(() => {
    if (!statusMessage) return;
    const timer = window.setTimeout(() => setStatusMessage(""), 3000);
    return () => window.clearTimeout(timer);
  }, [statusMessage]);

  async function refreshConversations(preferredConversationId?: string | null) {
    if (!familyId) return;
    const listing = await api.listConversations(familyId);
    setConversations(listing.items);
    const nextConversationId = preferredConversationId ?? selectedConversationId ?? listing.items[0]?.conversation_id ?? null;
    if (nextConversationId) {
      const detail = await api.getConversation(familyId, nextConversationId);
      setSelectedConversation(detail);
      setSelectedConversationId(nextConversationId);
    } else {
      setSelectedConversation(null);
      setSelectedConversationId(null);
    }
  }

  async function openConversation(conversationId: string) {
    if (!familyId) return;
    setSelectedConversationId(conversationId);
    setErrorMessage("");
    try {
      const detail = await api.getConversation(familyId, conversationId);
      setSelectedConversation(detail);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not open that conversation.");
    }
  }

  function setDraftValue(value: string) {
    setComposerText(value);
    if (!selectedConversationId) return;
    setDrafts((current) => ({ ...current, [selectedConversationId]: value }));
  }

  async function handleSendMessage(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!familyId || !selectedConversationId || sending) return;
    if (!composerText.trim() && !pendingAttachments.length) return;
    try {
      setSending(true);
      setErrorMessage("");
      const response = await api.sendMessage(familyId, selectedConversationId, {
        body_text: composerText.trim() || "Shared attachments",
        attachment_ids: pendingAttachments.map((attachment) => attachment.attachment_id),
        invoke_assistant: selectedConversation?.kind === "assistant" ? false : invokeAssistant,
        assistant_id: selectedAssistantId || undefined,
        quick_action_prefix: quickActionPrefix || undefined,
      });
      setSelectedConversation(response);
      setConversations((current) => current.map((item) => (item.conversation_id === response.conversation_id ? { ...item, ...response } : item)));
      setDraftValue("");
      setQuickActionPrefix(null);
      setPendingAttachments([]);
      setSelectedMessageId(null);
      setStatusMessage("Message sent.");
      void refreshConversations(selectedConversationId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not send that message.");
    } finally {
      setSending(false);
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!familyId || !selectedConversationId || !files?.length) return;
    try {
      setUploading(true);
      setErrorMessage("");
      const uploads = await Promise.all(Array.from(files).map((file) => api.uploadAttachment(familyId, selectedConversationId, file)));
      setPendingAttachments((current) => [...current, ...uploads.map((item) => item.attachment)]);
      setStatusMessage(`${uploads.length} attachment${uploads.length === 1 ? "" : "s"} ready to send.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not upload those files.");
    } finally {
      setUploading(false);
    }
  }

  async function handleInviteAssistant(assistantId: TopLevelAssistant, assistantMode: AssistantMode, setPrimary = false) {
    if (!familyId || !selectedConversation) return;
    try {
      const response = await api.inviteAssistant(familyId, selectedConversation.conversation_id, {
        assistant_id: assistantId,
        assistant_mode: assistantMode,
        set_primary: setPrimary,
      });
      setSelectedConversation(response);
      void refreshConversations(selectedConversation.conversation_id);
      setStatusMessage(`${assistantId === "caleb" ? "Caleb" : "Amelia"} updated.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not update the assistant.");
    }
  }

  async function handleRemoveParticipant(participantId: string) {
    if (!familyId || !selectedConversation) return;
    try {
      const response = await api.removeParticipant(familyId, selectedConversation.conversation_id, participantId);
      setSelectedConversation(response);
      void refreshConversations(selectedConversation.conversation_id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not remove that participant.");
    }
  }

  async function handleCreateSummary() {
    if (!familyId || !selectedConversation) return;
    try {
      const response = await api.createSummary(familyId, selectedConversation.conversation_id);
      setSelectedConversation(response);
      void refreshConversations(selectedConversation.conversation_id);
      setStatusMessage("Summary added.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not create a summary.");
    }
  }

  async function handleConvert(target: "tasks" | "note" | "plan") {
    if (!familyId || !selectedConversation) return;
    try {
      await api.convertConversation(familyId, selectedConversation.conversation_id, {
        target,
        title: `${selectedConversation.title} ${target}`,
      });
      await refreshConversations(selectedConversation.conversation_id);
      setStatusMessage(`${target === "tasks" ? "Task" : target === "note" ? "Note" : "Plan"} proposal drafted.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not draft that proposal.");
    }
  }

  async function handleActionMutation(actionId: string, type: "confirm" | "commit" | "cancel") {
    if (!familyId || !selectedConversation) return;
    try {
      if (type === "confirm") {
        await api.confirmAction(familyId, actionId);
      } else if (type === "commit") {
        await api.commitAction(familyId, actionId);
      } else {
        await api.cancelAction(familyId, actionId);
      }
      await refreshConversations(selectedConversation.conversation_id);
      setStatusMessage(`Proposal ${type}ed.`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not update that proposal.");
    }
  }

  async function handleShareSelectedMessage() {
    if (!familyId || !selectedMessageId || !shareTargetConversationId) return;
    try {
      await api.shareMessage(familyId, selectedMessageId, {
        target_conversation_id: shareTargetConversationId,
        note: shareNote || undefined,
      });
      setSelectedMessageId(null);
      setShareNote("");
      setStatusMessage("Message shared.");
      await refreshConversations(selectedConversationId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not share that message.");
    }
  }

  async function handleCreateConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!familyId || !context || creating) return;
    try {
      setCreating(true);
      setErrorMessage("");
      const humanParticipants = newConversationParticipantIds
        .map((personId) => context.persons.find((person) => person.person_id === personId))
        .filter((person): person is ViewerContextResponse["persons"][number] => Boolean(person))
        .map((person) => ({ person_id: person.person_id, display_name: person.display_name, role: "member" }));

      const kind: ConversationKind = newConversationMode === "shared" ? "hybrid" : "family";
      const assistantIds = newConversationMode === "shared" ? newSharedAssistants : [];
      const created = await api.createConversation(familyId, {
        kind,
        title: newConversationTitle || (newConversationMode === "shared" ? "Shared space" : "Family chat"),
        visibility_scope: "participants",
        space_type: newConversationMode === "shared" ? newSharedSpaceType : "none",
        assistant_ids: assistantIds,
        human_participants: humanParticipants,
        primary_assistant: assistantIds[0],
      });

      if (newConversationMode === "shared") {
        for (const assistantId of newSharedAssistants) {
          const mode = newSharedAssistantModes[assistantId];
          if (mode === "active") {
            await api.inviteAssistant(familyId, created.conversation_id, {
              assistant_id: assistantId,
              assistant_mode: "active",
              set_primary: assistantId === newSharedAssistants[0],
            });
          }
        }
      }

      setNewConversationMode("closed");
      setNewConversationTitle("");
      setNewConversationParticipantIds([]);
      setNewSharedAssistants(["amelia"]);
      setNewSharedAssistantModes({ caleb: "passive", amelia: "active" });
      await refreshConversations(created.conversation_id);
      setStatusMessage("Conversation created.");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not create that conversation.");
    } finally {
      setCreating(false);
    }
  }

  function toggleNewConversationParticipant(personId: string) {
    setNewConversationParticipantIds((current) =>
      current.includes(personId) ? current.filter((item) => item !== personId) : [...current, personId]
    );
  }

  function toggleSharedAssistant(assistantId: TopLevelAssistant) {
    setNewSharedAssistants((current) =>
      current.includes(assistantId) ? current.filter((item) => item !== assistantId) : [...current, assistantId]
    );
  }

  function visibleConversationsForSection(section: "assistant" | "family" | "spaces"): Conversation[] {
    const needle = deferredSearch.trim().toLowerCase();
    return conversations.filter((conversation) => {
      if (section === "assistant" && conversation.kind !== "assistant") return false;
      if (section === "family" && (conversation.kind === "assistant" || conversation.space_type !== "none")) return false;
      if (section === "spaces" && conversation.space_type === "none") return false;
      if (!needle) return true;
      return `${conversation.title} ${conversationPreview(conversation)}`.toLowerCase().includes(needle);
    });
  }

  const assistantChats = visibleConversationsForSection("assistant");
  const familyChats = visibleConversationsForSection("family");
  const sharedSpaces = visibleConversationsForSection("spaces");
  const selectedMessage = selectedConversation?.messages.find((message) => message.message_id === selectedMessageId) ?? null;
  const assistantParticipants = selectedConversation?.participants.filter((participant) => participant.participant_kind === "top_level_ai") ?? [];
  const humanParticipants = selectedConversation?.participants.filter((participant) => participant.participant_kind === "human") ?? [];

  if (loading) {
    return (
      <main className="workspace-shell loading-shell">
        <div className="viewer-orb orb-left" />
        <div className="viewer-orb orb-right" />
        <section className="loading-card">
          <p className="eyebrow">Chat</p>
          <h1>Preparing your family workspace…</h1>
          <p>Loading Caleb, Amelia, your family conversations, and the shared side panel.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <div className="viewer-orb orb-left" />
      <div className="viewer-orb orb-right" />
      <div className="viewer-orb orb-bottom" />
      <div className="workspace-frame">
        <aside className="panel sidebar-panel">
          <div className="sidebar-header">
            <p className="eyebrow">Chat</p>
            <h1>Shared conversation workspace</h1>
            <p>
              Human chat, Caleb, Amelia, and quiet domain-agent progress in one calm family command center.
            </p>
          </div>

          <div className="viewer-card">
            <div className="viewer-topline">
              <strong>{context?.family_slug || "family"}</strong>
              <span>{me?.email || "viewer"}</span>
            </div>
            <p>{statusMessage || "Choose a chat, invite an assistant when needed, and keep the thread connected to real work."}</p>
          </div>

          <label className="field">
            <span>Search chats</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by title or preview" />
          </label>

          <div className="action-strip">
            <button className="secondary-button" type="button" onClick={() => setNewConversationMode("family")}>
              New family chat
            </button>
            <button className="secondary-button" type="button" onClick={() => setNewConversationMode("shared")}>
              New shared space
            </button>
          </div>

          {newConversationMode !== "closed" ? (
            <form className="composer-card" onSubmit={handleCreateConversation}>
              <div className="card-header">
                <strong>{newConversationMode === "shared" ? "Shared space" : "Family chat"}</strong>
                <button className="ghost-button" type="button" onClick={() => setNewConversationMode("closed")}>
                  Close
                </button>
              </div>
              <label className="field">
                <span>Title</span>
                <input value={newConversationTitle} onChange={(event) => setNewConversationTitle(event.target.value)} placeholder="Give this chat a clear name" />
              </label>
              <div className="field">
                <span>People</span>
                <div className="toggle-grid">
                  {context?.persons
                    .filter((person) => person.person_id !== context.actor_person_id)
                    .map((person) => (
                      <label className="toggle-pill" key={person.person_id}>
                        <input
                          checked={newConversationParticipantIds.includes(person.person_id)}
                          onChange={() => toggleNewConversationParticipant(person.person_id)}
                          type="checkbox"
                        />
                        <span>{person.display_name}</span>
                      </label>
                    ))}
                </div>
              </div>
              {newConversationMode === "shared" ? (
                <>
                  <label className="field">
                    <span>Space focus</span>
                    <select value={newSharedSpaceType} onChange={(event) => setNewSharedSpaceType(event.target.value)}>
                      {SPACE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="field">
                    <span>Invite assistants</span>
                    <div className="assistant-create-grid">
                      {ASSISTANTS.map((assistant) => {
                        const selected = newSharedAssistants.includes(assistant.id);
                        return (
                          <div className="assistant-toggle-card" key={assistant.id}>
                            <label className="toggle-pill">
                              <input checked={selected} onChange={() => toggleSharedAssistant(assistant.id)} type="checkbox" />
                              <span>{assistant.label}</span>
                            </label>
                            {selected ? (
                              <div className="mini-button-row">
                                <button
                                  className={newSharedAssistantModes[assistant.id] === "passive" ? "tiny-button is-active" : "tiny-button"}
                                  onClick={() =>
                                    setNewSharedAssistantModes((current) => ({ ...current, [assistant.id]: "passive" }))
                                  }
                                  type="button"
                                >
                                  Passive
                                </button>
                                <button
                                  className={newSharedAssistantModes[assistant.id] === "active" ? "tiny-button is-active" : "tiny-button"}
                                  onClick={() =>
                                    setNewSharedAssistantModes((current) => ({ ...current, [assistant.id]: "active" }))
                                  }
                                  type="button"
                                >
                                  Active
                                </button>
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              ) : null}
              <button className="primary-button" disabled={creating} type="submit">
                {creating ? "Creating…" : "Create conversation"}
              </button>
            </form>
          ) : null}

          <section className="sidebar-group">
            <div className="group-header">
              <h2>Assistants</h2>
              <span>{assistantChats.length}</span>
            </div>
            {assistantChats.map((conversation) => (
              <button
                className={conversation.conversation_id === selectedConversationId ? "chat-row is-active" : "chat-row"}
                key={conversation.conversation_id}
                onClick={() => void openConversation(conversation.conversation_id)}
                type="button"
              >
                <div>
                  <strong>{conversation.title}</strong>
                  <p>{conversationPreview(conversation)}</p>
                </div>
                <span className="chat-badge">Assistant</span>
              </button>
            ))}
          </section>

          <section className="sidebar-group">
            <div className="group-header">
              <h2>Family Chats</h2>
              <span>{familyChats.length}</span>
            </div>
            {familyChats.map((conversation) => (
              <button
                className={conversation.conversation_id === selectedConversationId ? "chat-row is-active" : "chat-row"}
                key={conversation.conversation_id}
                onClick={() => void openConversation(conversation.conversation_id)}
                type="button"
              >
                <div>
                  <strong>{conversation.title}</strong>
                  <p>{conversationPreview(conversation)}</p>
                </div>
                <span className="chat-badge">{formatConversationKind(conversation)}</span>
              </button>
            ))}
          </section>

          <section className="sidebar-group">
            <div className="group-header">
              <h2>Shared Spaces</h2>
              <span>{sharedSpaces.length}</span>
            </div>
            {sharedSpaces.map((conversation) => (
              <button
                className={conversation.conversation_id === selectedConversationId ? "chat-row is-active" : "chat-row"}
                key={conversation.conversation_id}
                onClick={() => void openConversation(conversation.conversation_id)}
                type="button"
              >
                <div>
                  <strong>{conversation.title}</strong>
                  <p>{conversation.space_type} · {conversationPreview(conversation)}</p>
                </div>
                <span className="chat-badge">With Assistant</span>
              </button>
            ))}
          </section>
        </aside>

        <section className="panel thread-panel">
          {selectedConversation ? (
            <>
              <header className="thread-header">
                <div>
                  <p className="eyebrow">{formatConversationKind(selectedConversation)}</p>
                  <h2>{selectedConversation.title}</h2>
                  <p>
                    {selectedConversation.space_type !== "none" ? `${selectedConversation.space_type} space` : "Conversation"} · Updated{" "}
                    {formatDateTime(selectedConversation.updated_at)}
                  </p>
                </div>
                <div className="header-actions">
                  <button className="secondary-button" onClick={() => void handleCreateSummary()} type="button">
                    Summarize
                  </button>
                  <button className="secondary-button" onClick={() => void handleConvert("tasks")} type="button">
                    Convert to tasks
                  </button>
                  <button className="secondary-button" onClick={() => void handleConvert("note")} type="button">
                    Save as note
                  </button>
                  <button className="secondary-button" onClick={() => void handleConvert("plan")} type="button">
                    Make plan
                  </button>
                </div>
              </header>

              <div className="inline-activity-strip">
                {selectedConversation.domain_activity.slice(0, 4).map((activity) => (
                  <div className={`activity-pill activity-${activity.state}`} key={activity.activity_id}>
                    <strong>{activity.agent_name}</strong>
                    <span>{activity.summary}</span>
                  </div>
                ))}
              </div>

              <div className="thread-scroll">
                {selectedConversation.messages.map((message) => (
                  <button
                    className={messageClass(message, selectedMessageId === message.message_id)}
                    key={message.message_id}
                    onClick={() => setSelectedMessageId(message.message_id)}
                    type="button"
                  >
                    <div className="message-meta">
                      <strong>{message.sender_label}</strong>
                      <span>{formatDateTime(message.created_at)}</span>
                    </div>
                    {message.blocks.length ? (
                      <div className="message-blocks">
                        {message.blocks.map((block) => {
                          if (block.block_type === "approval_card") {
                            return (
                              <div className="rich-card approval-card" key={block.block_id}>
                                <span className="state-pill">{String(block.data.status || "proposed")}</span>
                                <p>{String(block.data.summary || message.body_text || "Draft action proposal")}</p>
                              </div>
                            );
                          }
                          if (block.block_type === "summary_card") {
                            return (
                              <div className="rich-card summary-card" key={block.block_id}>
                                <strong>Summary card</strong>
                                <p>{block.text_content || message.body_text || "Shared summary"}</p>
                              </div>
                            );
                          }
                          if (block.block_type === "agent_activity") {
                            return (
                              <div className="rich-card activity-card" key={block.block_id}>
                                <strong>{String(block.data.summary || "Agent activity")}</strong>
                                <p>{message.body_text || "The system is working in the background."}</p>
                              </div>
                            );
                          }
                          if (block.block_type !== "markdown") {
                            return (
                              <div className="rich-card generic-card" key={block.block_id}>
                                <strong>{block.block_type.replace("_", " ")}</strong>
                                <p>{block.text_content || blockSummary(message)}</p>
                              </div>
                            );
                          }
                          return (
                            <p className="message-copy" key={block.block_id}>
                              {block.text_content || message.body_text}
                            </p>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="message-copy">{message.body_text}</p>
                    )}
                    {message.attachments.length ? (
                      <div className="attachment-list">
                        {message.attachments.map((attachment) => (
                          <span className="attachment-chip" key={attachment.attachment_id}>
                            {attachment.file_name}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </button>
                ))}
              </div>

              <form className="composer-panel" onSubmit={handleSendMessage}>
                <div className="quick-action-row">
                  {QUICK_ACTIONS.map((action) => (
                    <button
                      className={quickActionPrefix === action.prefix ? "quick-action is-active" : "quick-action"}
                      key={action.prefix}
                      onClick={() => {
                        setQuickActionPrefix(action.prefix);
                        composerRef.current?.focus();
                      }}
                      type="button"
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
                {quickActionPrefix ? (
                  <div className="composer-hint">
                    <span>{quickActionPrefix}</span>
                    <button className="ghost-button" onClick={() => setQuickActionPrefix(null)} type="button">
                      Clear
                    </button>
                  </div>
                ) : null}
                <textarea
                  className="composer-input"
                  onChange={(event) => setDraftValue(event.target.value)}
                  onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void handleSendMessage();
                    }
                  }}
                  placeholder="Write a message, mention @Caleb or @Amelia, or keep the chat human-only."
                  ref={composerRef}
                  rows={4}
                  value={composerText}
                />
                <div className="composer-controls">
                  <label className="upload-pill">
                    <input onChange={(event) => void handleUpload(event.target.files)} type="file" multiple />
                    {uploading ? "Uploading…" : "Add files"}
                  </label>
                  {selectedConversation.kind !== "assistant" ? (
                    <>
                      <label className="checkbox-inline">
                        <input checked={invokeAssistant} onChange={(event) => setInvokeAssistant(event.target.checked)} type="checkbox" />
                        <span>Ask the room assistant on send</span>
                      </label>
                      <select
                        disabled={selectedConversation.kind === "family" && !assistantParticipants.length}
                        onChange={(event) => setSelectedAssistantId((event.target.value as TopLevelAssistant) || "")}
                        value={selectedAssistantId}
                      >
                        <option value="">Primary assistant</option>
                        {assistantParticipants.map((participant) => (
                          <option key={participant.participant_id} value={participant.top_level_assistant || ""}>
                            {participant.display_name}
                          </option>
                        ))}
                      </select>
                    </>
                  ) : null}
                  <button className="primary-button" disabled={sending} type="submit">
                    {sending ? "Sending…" : "Send"}
                  </button>
                </div>
                {pendingAttachments.length ? (
                  <div className="attachment-list">
                    {pendingAttachments.map((attachment) => (
                      <span className="attachment-chip" key={attachment.attachment_id}>
                        {attachment.file_name}
                      </span>
                    ))}
                  </div>
                ) : null}
              </form>
            </>
          ) : (
            <div className="empty-panel">
              <p className="eyebrow">Chat</p>
              <h2>Select a conversation</h2>
              <p>Choose Caleb, Amelia, a family chat, or a shared planning space from the left rail.</p>
            </div>
          )}
        </section>

        <aside className="panel context-panel">
          <div className="context-header">
            <p className="eyebrow">Context</p>
            <h2>Related state</h2>
            <p>See who is here, what the system is doing, and what still needs approval.</p>
          </div>

          {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}

          {selectedConversation ? (
            <>
              <section className="context-card">
                <div className="card-header">
                  <strong>Assistants</strong>
                </div>
                <div className="participant-list">
                  {ASSISTANTS.map((assistant) => {
                    const participant = assistantParticipant(selectedConversation, assistant.id);
                    return (
                      <div className="participant-card" key={assistant.id}>
                        <div>
                          <strong>{assistant.label}</strong>
                          <p>
                            {participant
                              ? `${participant.assistant_mode || "passive"} mode${selectedConversation.primary_assistant_id === participant.participant_id ? " · primary" : ""}`
                              : "Not in this conversation"}
                          </p>
                        </div>
                        <div className="mini-button-row">
                          <button className="tiny-button" onClick={() => void handleInviteAssistant(assistant.id, "passive")} type="button">
                            Passive
                          </button>
                          <button className="tiny-button" onClick={() => void handleInviteAssistant(assistant.id, "active", true)} type="button">
                            Active
                          </button>
                          {participant ? (
                            <button className="tiny-button danger" onClick={() => void handleRemoveParticipant(participant.participant_id)} type="button">
                              Remove
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="context-card">
                <div className="card-header">
                  <strong>People</strong>
                </div>
                <div className="participant-list">
                  {humanParticipants.map((participant) => (
                    <div className="participant-card" key={participant.participant_id}>
                      <div>
                        <strong>{participant.display_name}</strong>
                        <p>{participant.role}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="context-card">
                <div className="card-header">
                  <strong>Summary so far</strong>
                </div>
                {selectedConversation.summaries.length ? (
                  <div className="stack-list">
                    {selectedConversation.summaries.slice(-3).reverse().map((summary) => (
                      <article className="summary-panel" key={summary.summary_id}>
                        <p>{summary.summary}</p>
                        {summary.decisions.length ? <span className="meta-chip">{summary.decisions.length} decisions</span> : null}
                        {summary.open_questions.length ? <span className="meta-chip">{summary.open_questions.length} open questions</span> : null}
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="muted-copy">No summary yet. Use Summarize in the thread header when the conversation gets long.</p>
                )}
              </section>

              <section className="context-card">
                <div className="card-header">
                  <strong>Approvals</strong>
                </div>
                {selectedConversation.action_proposals.length ? (
                  <div className="stack-list">
                    {selectedConversation.action_proposals.map((proposal: ActionProposal) => (
                      <article className="proposal-card" key={proposal.action_id}>
                        <div className="proposal-topline">
                          <strong>{proposal.title}</strong>
                          <span className={`state-pill state-${proposal.status}`}>{proposal.status}</span>
                        </div>
                        <p>{proposal.summary}</p>
                        <div className="mini-button-row">
                          <button className="tiny-button" onClick={() => void handleActionMutation(proposal.action_id, "confirm")} type="button">
                            Confirm
                          </button>
                          <button className="tiny-button" onClick={() => void handleActionMutation(proposal.action_id, "commit")} type="button">
                            Commit
                          </button>
                          <button className="tiny-button danger" onClick={() => void handleActionMutation(proposal.action_id, "cancel")} type="button">
                            Cancel
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="muted-copy">No pending approvals in this conversation.</p>
                )}
              </section>

              <section className="context-card">
                <div className="card-header">
                  <strong>Domain work</strong>
                </div>
                {selectedConversation.domain_activity.length ? (
                  <div className="stack-list">
                    {selectedConversation.domain_activity.map((activity) => (
                      <article className="activity-summary-card" key={activity.activity_id}>
                        <div className="proposal-topline">
                          <strong>{activity.agent_name}</strong>
                          <span className={`state-pill state-${activity.state}`}>{activity.state}</span>
                        </div>
                        <p>{activity.summary}</p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="muted-copy">Domain agents only appear here when background work is in progress or has completed.</p>
                )}
              </section>

              <section className="context-card">
                <div className="card-header">
                  <strong>Share selected message</strong>
                </div>
                {selectedMessage ? (
                  <>
                    <div className="selected-message-preview">
                      <strong>{selectedMessage.sender_label}</strong>
                      <p>{blockSummary(selectedMessage)}</p>
                    </div>
                    <label className="field">
                      <span>Target conversation</span>
                      <select value={shareTargetConversationId} onChange={(event) => setShareTargetConversationId(event.target.value)}>
                        <option value="">Choose a destination</option>
                        {conversations
                          .filter((conversation) => conversation.conversation_id !== selectedConversation.conversation_id)
                          .map((conversation) => (
                            <option key={conversation.conversation_id} value={conversation.conversation_id}>
                              {conversation.title}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>Note</span>
                      <textarea
                        onChange={(event) => setShareNote(event.target.value)}
                        placeholder="Optional context to send with the share"
                        rows={3}
                        value={shareNote}
                      />
                    </label>
                    <button className="primary-button" onClick={() => void handleShareSelectedMessage()} type="button">
                      Share to chat
                    </button>
                  </>
                ) : (
                  <p className="muted-copy">Click any message in the thread to share it into another family or hybrid conversation.</p>
                )}
              </section>
            </>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
