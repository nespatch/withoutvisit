// clip_bot_worker.js — one Telegram bot for the clipboard utility.
//
// The desktop app never sees the bot token. A person presses Start once.
// Later copies are delivered to that chat with the bot.
//
// Deploy this file on its own, not inside the PDF worker.
// Worker name: clip-bot
//
// Secret:
//   TELEGRAM_BOT_TOKEN   from @BotFather
//
// Binding:
//   KV namespace, variable name LINKS
//
// After the first deploy, open https://<worker>/setup once.
// That calls setWebhook. Then the desktop app can connect.

const LIMIT = 4000;

function json(data, status) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: { "content-type": "application/json" },
  });
}

async function tg(env, method, body) {
  const token = env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    throw new Error("TELEGRAM_BOT_TOKEN is missing");
  }
  const response = await fetch("https://api.telegram.org/bot" + token + "/" + method, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.description || "Telegram request failed");
  }
  return data;
}

function chunks(text) {
  const parts = [];
  let rest = String(text || "");
  while (rest) {
    parts.push(rest.slice(0, LIMIT));
    rest = rest.slice(LIMIT);
  }
  return parts;
}

async function sendPhoto(env, chatId, file, caption) {
  const token = env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    throw new Error("TELEGRAM_BOT_TOKEN is missing");
  }
  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append("disable_notification", "true");
  if (caption) {
    form.append("caption", String(caption).slice(0, 1024));
  }
  const name = (file && file.name) || "image.png";
  const gif = name.toLowerCase().endsWith(".gif");
  form.append(gif ? "animation" : "photo", file, name);
  const method = gif ? "sendAnimation" : "sendPhoto";
  const response = await fetch("https://api.telegram.org/bot" + token + "/" + method, {
    method: "POST",
    body: form,
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.description || "Telegram request failed");
  }
  return data;
}

async function sendText(env, chatId, text) {
  const parts = chunks(text);
  for (let i = 0; i < parts.length; i++) {
    await tg(env, "sendMessage", {
      chat_id: chatId,
      text: parts[i],
      disable_notification: true,
      link_preview_options: { is_disabled: true },
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (!env.LINKS) {
        return json({ error: "KV binding LINKS is missing" }, 500);
      }
      if (request.method === "GET" && url.pathname === "/bot") {
        const me = await tg(env, "getMe");
        return json({ username: me.result && me.result.username });
      }
      if (request.method === "GET" && url.pathname === "/link") {
        const code = url.searchParams.get("code") || "";
        if (!/^[a-f0-9]{16,}$/.test(code)) {
          return json({ linked: false });
        }
        const chat = await env.LINKS.get("link:" + code);
        return json({ linked: !!chat });
      }
      if (request.method === "POST" && url.pathname === "/send") {
        const ctype = request.headers.get("content-type") || "";
        if (ctype.indexOf("multipart/form-data") !== -1) {
          const form = await request.formData();
          const code = String(form.get("code") || "");
          const photo = form.get("photo");
          const caption = String(form.get("caption") || "");
          if (!/^[a-f0-9]{16,}$/.test(code) || !photo) {
            return json({ error: "Missing image" }, 400);
          }
          if (photo.size && photo.size > 10 * 1024 * 1024) {
            return json({ error: "Image is too big." }, 400);
          }
          const chat = await env.LINKS.get("link:" + code);
          if (!chat) {
            return json({ error: "Not linked" }, 404);
          }
          await sendPhoto(env, chat, photo, caption);
          return json({ ok: true });
        }
        const body = await request.json();
        const code = String(body.code || "");
        const text = String(body.text || "");
        if (!/^[a-f0-9]{16,}$/.test(code) || !text.trim()) {
          return json({ error: "Missing text" }, 400);
        }
        const chat = await env.LINKS.get("link:" + code);
        if (!chat) {
          return json({ error: "Not linked" }, 404);
        }
        await sendText(env, chat, text);
        return json({ ok: true });
      }
      if (request.method === "POST" && url.pathname === "/hook") {
        const update = await request.json();
        const message = update.message || {};
        const text = String(message.text || "");
        const match = text.match(/^\/start(?:@\w+)?(?:\s+([a-f0-9]{16,}))?/i);
        if (match && message.chat && message.chat.id) {
          const code = (match[1] || "").toLowerCase();
          if (!code) {
            await tg(env, "sendMessage", {
              chat_id: message.chat.id,
              text: "Open the link from the app, then press Start.",
            });
          } else {
            await env.LINKS.put("link:" + code, String(message.chat.id));
            await tg(env, "sendMessage", {
              chat_id: message.chat.id,
              text: "Connected. Copies will arrive here.",
            });
          }
        }
        return new Response("ok");
      }
      if ((request.method === "GET" || request.method === "POST") && url.pathname === "/setup") {
        const hook = new URL(request.url);
        hook.pathname = "/hook";
        hook.search = "";
        const result = await tg(env, "setWebhook", { url: hook.toString() });
        return json({ ok: true, webhook: hook.toString(), result: result.result });
      }
      return new Response("clip bot");
    } catch (error) {
      return json({ error: String(error && error.message || error).slice(0, 200) }, 500);
    }
  },
};
