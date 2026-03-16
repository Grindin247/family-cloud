import { readFile } from "node:fs/promises";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

type LaunchTile = "new-doc" | "whiteboard" | "notes";

function familyDomain(): string {
  return (process.env.NEXT_PUBLIC_FAMILY_DOMAIN || "").trim();
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
  const match = xml.match(new RegExp(`<${tag}>([^<]+)</${tag}>`));
  return match?.[1] ?? null;
}

async function createTextDocument(baseUrl: string): Promise<string> {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
  const { username, password } = await nextcloudAuth();
  const fileName = `Family Cloud Doc ${nowStamp()}.md`;
  const response = await fetch(`${baseUrl}/ocs/v2.php/apps/files/api/v1/directEditing/create`, {
    method: "POST",
    headers: {
      Authorization: authHeader(username, password),
      "OCS-APIRequest": "true",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      path: fileName,
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
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
  const { username, password } = await nextcloudAuth();
  const fileName = `Family Cloud Whiteboard ${nowStamp()}.whiteboard`;
  const filePath = encodeURIComponent(fileName);
  const response = await fetch(`${baseUrl}/remote.php/dav/files/${encodeURIComponent(username)}/${filePath}`, {
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

export async function GET(_: NextRequest, context: { params: { tile: string } }) {
  const tile = context.params.tile as LaunchTile;
  const baseUrl = nextcloudBaseUrl();

  try {
    if (tile === "new-doc") {
      return NextResponse.redirect(await createTextDocument(baseUrl));
    }

    if (tile === "whiteboard") {
      return NextResponse.redirect(await createWhiteboard(baseUrl));
    }

    if (tile === "notes") {
      return NextResponse.redirect(noteUrl(baseUrl));
    }
  } catch (error) {
    console.error(`Launch failed for ${tile}`, error);
  }

  return NextResponse.redirect(baseUrl);
}
