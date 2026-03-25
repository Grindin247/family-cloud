import { readFile } from "node:fs/promises";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

type LaunchTile = "new-doc" | "whiteboard" | "notes" | "process-inbox";

type InboxEntry = {
  path: string;
  name: string;
  size: number | null;
  lastModified: number | null;
  contentType: string;
  lockOwner: string;
  isDirectory: boolean;
};

const AUTO_GEN_DOC_PATTERN = /^Family Cloud Doc \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.md$/;
const AUTO_GEN_WHITEBOARD_PATTERN = /^Family Cloud Whiteboard \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.whiteboard$/;
const DEFAULT_CLEANUP_MINUTES = 30;

function familyDomain(): string {
  return (process.env.NEXT_PUBLIC_FAMILY_DOMAIN || "").trim();
}

function fileApiBaseUrl(): string {
  return (process.env.HOME_PORTAL_FILE_API_BASE_URL || process.env.HOME_PORTAL_DECISION_API_BASE_URL || "http://file-api:8000/v1")
    .trim()
    .replace(/\/+$/, "");
}

function inboxFamilyId(): number {
  const raw = process.env.HOME_PORTAL_FILE_AGENT_FAMILY_ID || process.env.FILE_AGENT_FAMILY_ID || "2";
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error("Missing valid HOME_PORTAL_FILE_AGENT_FAMILY_ID or FILE_AGENT_FAMILY_ID");
  }
  return parsed;
}

function fallbackAutomationActor(): string {
  return (process.env.HOME_PORTAL_FILE_AGENT_ACTOR || process.env.FILE_AGENT_ACTOR || "").trim().toLowerCase();
}

function nextcloudBaseUrl(): string {
  const explicit = (process.env.NEXTCLOUD_BASE_URL || "").trim();
  if (explicit) return explicit.replace(/\/+$/, "");

  const domain = familyDomain();
  if (!domain) {
    throw new Error("Missing NEXTCLOUD_BASE_URL or NEXT_PUBLIC_FAMILY_DOMAIN");
  }

  return `https://nextcloud.${domain}`;
}

async function secret(path: string): Promise<string> {
  return (await readFile(path, "utf8")).trim();
}

async function nextcloudAuth(): Promise<{ username: string; password: string }> {
  const username = process.env.NEXTCLOUD_AUTOMATION_USERNAME?.trim() || (await secret("/run/secrets/nextcloud_mcp_username"));
  const password = process.env.NEXTCLOUD_AUTOMATION_PASSWORD?.trim() || (await secret("/run/secrets/nextcloud_mcp_app_password"));
  return { username, password };
}

function authHeader(username: string, password: string): string {
  return `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
}

function nowStamp(): string {
  const date = new Date();
  return date
    .toISOString()
    .replace("T", " ")
    .replace(/\.\d{3}Z$/, "")
    .replace(/:/g, "-");
}

function xmlValue(xml: string, tag: string): string | null {
  const escapedTag = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = xml.match(new RegExp(`<${escapedTag}>([\\s\\S]*?)</${escapedTag}>`));
  return decodeXml(match?.[1] ?? null);
}

function decodeXml(value: string | null): string | null {
  if (!value) return value;
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

function encodeWebDavPath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function allowSelfSignedTls(): void {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
}

function buildInboxSummary(payload: Record<string, unknown>): string {
  const processed = Number(payload.processed || 0);
  const indexed = Number(payload.indexed || 0);
  const unfiled = Number(payload.unfiled || 0);
  const locked = Number(payload.skipped_locked || 0);
  const recent = Number(payload.skipped_recent || 0);
  const parts = [`Processed ${processed} item${processed === 1 ? "" : "s"}`];
  if (indexed > 0) {
    parts.push(`indexed ${indexed}`);
  }
  if (unfiled > 0) {
    parts.push(`left ${unfiled} in Unfiled`);
  }
  if (locked > 0) {
    parts.push(`skipped ${locked} locked`);
  }
  if (recent > 0) {
    parts.push(`skipped ${recent} still-recent`);
  }
  return parts.join(", ") + ".";
}

function buildInboxDetail(payload: Record<string, unknown>): string | null {
  const results = Array.isArray(payload.results) ? payload.results : [];
  const conflicts = Array.isArray(payload.conflicts) ? payload.conflicts : [];
  const first = results[0];
  if (first && typeof first === "object") {
    const title = typeof first.title === "string" && first.title.trim() ? first.title.trim() : "First filed item";
    const folder = typeof first.folder === "string" && first.folder.trim() ? first.folder.trim() : null;
    const sourcePath = typeof first.source_path === "string" ? first.source_path : null;
    if (folder && sourcePath) {
      return `${title} was filed from ${sourcePath} into ${folder}.`;
    }
    if (folder) {
      return `${title} was filed into ${folder}.`;
    }
  }
  if (conflicts.length > 0) {
    return `${conflicts.length} naming conflict${conflicts.length === 1 ? "" : "s"} need review.`;
  }
  return null;
}

function redirectHomeWithInboxStatus(
  values: {
    status: string;
    summary: string;
    detail?: string | null;
  },
): NextResponse {
  const params = new URLSearchParams();
  params.set("inboxStatus", values.status);
  params.set("inboxSummary", values.summary);
  if (values.detail) {
    params.set("inboxDetail", values.detail);
  }
  return redirectHome(params);
}

function redirectHome(params?: URLSearchParams): NextResponse {
  const location = params?.size ? `/?${params.toString()}` : "/";
  return new NextResponse(null, {
    status: 303,
    headers: {
      Location: location,
    },
  });
}

function cleanupWindowMs(): number {
  const rawValue = Number.parseInt(process.env.HOME_PORTAL_AUTOGEN_CLEANUP_MINUTES || "", 10);
  const minutes = Number.isFinite(rawValue) && rawValue > 0 ? rawValue : DEFAULT_CLEANUP_MINUTES;
  return minutes * 60 * 1000;
}

function decodeWebDavHref(username: string, href: string): string | null {
  const marker = `/remote.php/dav/files/${encodeURIComponent(username)}`;
  const index = href.indexOf(marker);
  if (index === -1) return null;
  const suffix = href.slice(index + marker.length);
  const decoded = suffix
    .split("/")
    .map((segment) => decodeURIComponent(segment))
    .join("/");
  return decoded.startsWith("/") ? decoded : `/${decoded}`;
}

function xmlBlocks(xml: string, tag: string): string[] {
  const escapedTag = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return Array.from(xml.matchAll(new RegExp(`<${escapedTag}\\b[\\s\\S]*?</${escapedTag}>`, "g"))).map((match) => match[0]);
}

async function listInboxEntries(baseUrl: string, username: string, password: string, path: string): Promise<InboxEntry[]> {
  const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${encodeWebDavPath(path)}`, {
    method: "PROPFIND",
    headers: {
      Authorization: authHeader(username, password),
      Depth: "1",
      "Content-Type": "application/xml",
    },
    body:
      '<?xml version="1.0"?>' +
      '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">' +
      "<d:prop>" +
      "<d:getcontentlength/>" +
      "<d:getlastmodified/>" +
      "<d:resourcetype/>" +
      "<d:getcontenttype/>" +
      "<oc:fileid/>" +
      "<oc:lock-owner-displayname/>" +
      "<oc:lock-owner/>" +
      "</d:prop>" +
      "</d:propfind>",
    cache: "no-store",
  });

  if (response.status === 404) {
    return [];
  }

  if (!response.ok) {
    throw new Error(`Inbox listing failed (${response.status})`);
  }

  const xml = await response.text();
  const blocks = xmlBlocks(xml, "d:response");

  return blocks
    .map((block, index) => {
      const href = xmlValue(block, "d:href");
      const itemPath = href ? decodeWebDavHref(username, href) : null;
      if (!itemPath || index === 0 || itemPath === path) {
        return null;
      }

      const sizeValue = xmlValue(block, "d:getcontentlength");
      const size = sizeValue ? Number.parseInt(sizeValue, 10) : null;
      const lastModifiedValue = xmlValue(block, "d:getlastmodified");
      const lastModified = lastModifiedValue ? Date.parse(lastModifiedValue) : null;
      const name = itemPath.split("/").filter(Boolean).at(-1) || itemPath;

      return {
        path: itemPath,
        name,
        size: Number.isFinite(size) ? size : null,
        lastModified: Number.isFinite(lastModified) ? lastModified : null,
        contentType: xmlValue(block, "d:getcontenttype") || "",
        lockOwner: xmlValue(block, "oc:lock-owner-displayname") || xmlValue(block, "oc:lock-owner") || "",
        isDirectory: /<d:collection\s*\/>/i.test(block),
      } satisfies InboxEntry;
    })
    .filter((entry): entry is InboxEntry => Boolean(entry));
}

async function readFileText(baseUrl: string, username: string, password: string, path: string): Promise<string> {
  const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${encodeWebDavPath(path)}`, {
    method: "GET",
    headers: {
      Authorization: authHeader(username, password),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Read failed for ${path} (${response.status})`);
  }

  return response.text();
}

async function deleteFile(baseUrl: string, username: string, password: string, path: string): Promise<void> {
  const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${encodeWebDavPath(path)}`, {
    method: "DELETE",
    headers: {
      Authorization: authHeader(username, password),
    },
    cache: "no-store",
  });

  if (!response.ok && response.status !== 404) {
    throw new Error(`Delete failed for ${path} (${response.status})`);
  }
}

function isStale(entry: InboxEntry): boolean {
  if (!entry.lastModified) return false;
  return Date.now() - entry.lastModified >= cleanupWindowMs();
}

async function isEmptyAutoGeneratedFile(baseUrl: string, username: string, password: string, entry: InboxEntry): Promise<boolean> {
  if (entry.isDirectory || entry.lockOwner || !isStale(entry)) {
    return false;
  }

  if (AUTO_GEN_DOC_PATTERN.test(entry.name)) {
    return entry.size === 0;
  }

  if (AUTO_GEN_WHITEBOARD_PATTERN.test(entry.name) && (entry.size === 2 || entry.size === 0)) {
    const content = await readFileText(baseUrl, username, password, entry.path);
    return content.trim() === "{}";
  }

  return false;
}

async function cleanupStaleAutoGeneratedInboxFiles(baseUrl: string, username: string, password: string): Promise<number> {
  const entries = await listInboxEntries(baseUrl, username, password, "/Notes/Inbox");
  let removed = 0;

  for (const entry of entries) {
    if (!(await isEmptyAutoGeneratedFile(baseUrl, username, password, entry))) {
      continue;
    }

    await deleteFile(baseUrl, username, password, entry.path);
    removed += 1;
  }

  return removed;
}

async function ensureDirectory(baseUrl: string, username: string, password: string, path: string): Promise<void> {
  const segments = path.split("/").filter(Boolean);
  let current = "";
  for (const segment of segments) {
    current = `${current}/${segment}`;
    const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${encodeWebDavPath(current)}`, {
      method: "MKCOL",
      headers: {
        Authorization: authHeader(username, password),
      },
      cache: "no-store",
    });
    if (!response.ok && response.status !== 405) {
      throw new Error(`MKCOL failed for ${current} (${response.status})`);
    }
  }
}

async function createTextDocument(baseUrl: string): Promise<string> {
  allowSelfSignedTls();
  const { username, password } = await nextcloudAuth();
  await ensureDirectory(baseUrl, username, password, "/Notes/Inbox");
  await cleanupStaleAutoGeneratedInboxFiles(baseUrl, username, password);
  const fileName = `Family Cloud Doc ${nowStamp()}.md`;
  const response = await fetch(`${baseUrl}/ocs/v2.php/apps/files/api/v1/directEditing/create`, {
    method: "POST",
    headers: {
      Authorization: authHeader(username, password),
      "OCS-APIRequest": "true",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      path: `Notes/Inbox/${fileName}`,
      editorId: "text",
      creatorId: "textdocument",
    }),
    cache: "no-store",
  });

  const text = await response.text();
  const url = xmlValue(text, "url");
  if (!response.ok || !url) {
    throw new Error(`Direct editing create failed (${response.status})`);
  }

  return url;
}

async function createWhiteboard(baseUrl: string): Promise<string> {
  allowSelfSignedTls();
  const { username, password } = await nextcloudAuth();
  await ensureDirectory(baseUrl, username, password, "/Notes/Inbox");
  await cleanupStaleAutoGeneratedInboxFiles(baseUrl, username, password);
  const filePath = `Notes/Inbox/Family Cloud Whiteboard ${nowStamp()}.whiteboard`;
  const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${encodeWebDavPath(filePath)}`, {
    method: "PUT",
    headers: {
      Authorization: authHeader(username, password),
      "Content-Type": "application/json",
    },
    body: "{}",
    cache: "no-store",
  });

  const fileId = response.headers.get("oc-fileid");
  if (!response.ok || !fileId) {
    throw new Error(`Whiteboard create failed (${response.status})`);
  }

  return `${baseUrl}/f/${encodeURIComponent(fileId)}`;
}

function noteUrl(baseUrl: string): string {
  return `${baseUrl}/index.php/apps/notes/new`;
}

async function processInbox(request: NextRequest): Promise<NextResponse> {
  allowSelfSignedTls();
  const actor =
    request.headers.get("x-forwarded-user")?.trim().toLowerCase() ||
    request.headers.get("x-dev-user")?.trim().toLowerCase() ||
    fallbackAutomationActor();
  if (!actor) {
    return redirectHomeWithInboxStatus({
      status: "failed",
      summary: "Inbox processing could not start.",
      detail: "No authenticated user or fallback automation actor was available.",
    });
  }

  try {
    const familyId = inboxFamilyId();
    const response = await fetch(`${fileApiBaseUrl()}/families/${familyId}/files/process-inbox`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-User": actor,
        "X-Dev-User": actor,
      },
      body: JSON.stringify({
        actor,
        include_dashboard_docs: true,
        respect_idle_window: true,
        source: "home-portal",
      }),
      cache: "no-store",
    });

    let payload: Record<string, unknown> = {};
    try {
      payload = (await response.json()) as Record<string, unknown>;
    } catch {
      payload = {};
    }

    if (!response.ok) {
      const detail =
        (typeof payload.detail === "string" && payload.detail) ||
        `Decision API returned ${response.status}.`;
      return redirectHomeWithInboxStatus({
        status: "failed",
        summary: "Inbox processing failed.",
        detail,
      });
    }

    return redirectHomeWithInboxStatus({
      status: typeof payload.status === "string" ? payload.status : "completed",
      summary: buildInboxSummary(payload),
      detail: buildInboxDetail(payload),
    });
  } catch (error) {
    return redirectHomeWithInboxStatus({
      status: "failed",
      summary: "Inbox processing failed.",
      detail: error instanceof Error ? error.message : "Unexpected inbox processing error.",
    });
  }
}

export async function GET(request: NextRequest, context: { params: { tile: string } }) {
  const tile = context.params.tile as LaunchTile;

  try {
    if (tile === "process-inbox") {
      return redirectHome();
    }

    const baseUrl = nextcloudBaseUrl();
    if (tile === "notes") {
      return NextResponse.redirect(noteUrl(baseUrl));
    }
  } catch (error) {
    console.error(`Launch failed for ${tile}`, error);
  }

  try {
    return NextResponse.redirect(nextcloudBaseUrl());
  } catch {
    return redirectHome();
  }
}

export async function POST(request: NextRequest, context: { params: { tile: string } }) {
  const tile = context.params.tile as LaunchTile;

  try {
    if (tile === "process-inbox") {
      return await processInbox(request);
    }

    const baseUrl = nextcloudBaseUrl();
    if (tile === "new-doc") {
      return NextResponse.redirect(await createTextDocument(baseUrl), 303);
    }

    if (tile === "whiteboard") {
      return NextResponse.redirect(await createWhiteboard(baseUrl), 303);
    }

    if (tile === "notes") {
      return NextResponse.redirect(noteUrl(baseUrl), 303);
    }
  } catch (error) {
    console.error(`Launch failed for ${tile}`, error);
  }

  try {
    return NextResponse.redirect(nextcloudBaseUrl(), 303);
  } catch {
    return redirectHome();
  }
}
