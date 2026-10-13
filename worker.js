// Cloudflare Worker: serves the static site from ./public and answers chat
// questions at POST /api/ask with a free Workers AI model (no API key needed).

const RULES = `You are the assistant on "Korkovahti", a page that helps home-loan borrowers (mainly in Finland, also other euro-area countries) understand Euribor.
Answer from the page data below plus general knowledge of how Euribor, the ECB and mortgages work. Rules:
- Be brief: under 140 words unless asked for more. Plain text only, no Markdown, no headings.
- Use the numbers exactly as given in the page data. Never invent a rate or a payment.
- The outlook is what markets price in, not a forecast. Say so and mention the uncertainty whenever you use it.
- Do not tell the person what to do with their money. Lay out the trade-offs and what to check with their bank.
- If the data does not cover something (for example news events), say you cannot see it here.
- Only answer questions about Euribor, interest rates and home loans. Politely decline anything else.
- Reply in the language the person writes in.`;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/ask") return env.ASSETS.fetch(request);
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);

    // Only the site itself may use the chat.
    const origin = request.headers.get("Origin");
    if (!origin || new URL(origin).host !== url.host) return json({ error: "forbidden" }, 403);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad_request" }, 400); }

    const context = String(body.context || "").slice(0, 6000);
    const messages = [{ role: "system", content: RULES + "\n\nPAGE DATA\n" + context }];
    for (const t of Array.isArray(body.turns) ? body.turns.slice(-8) : []) {
      if ((t.role === "user" || t.role === "assistant") && typeof t.content === "string" && t.content.trim())
        messages.push({ role: t.role, content: t.content.slice(0, 1500) });
    }
    if (messages.length < 2 || messages[messages.length - 1].role !== "user") return json({ error: "bad_request" }, 400);

    try {
      const out = await env.AI.run(env.MODEL, { messages, max_tokens: 450, temperature: 0.3 });
      const answer = String(out.response ?? out.choices?.[0]?.message?.content ?? "").trim();
      return answer ? json({ answer }) : json({ error: "empty_completion" }, 502);
    } catch (e) {
      // The free daily allowance is a hard cap: once it is used up, calls fail until midnight UTC.
      const busy = /limit|quota|allocation|neurons|429/i.test(String(e && e.message));
      return json({ error: busy ? "busy" : "upstream_error" }, busy ? 429 : 502);
    }
  },
};
