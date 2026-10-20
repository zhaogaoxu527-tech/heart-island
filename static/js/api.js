/**
 * 心屿 · 前端 API 客户端（登录版）
 * 统一处理会话 Cookie、超时、中文错误与后端的 { ok, data, error } 结构。
 */

const API_ROOT = "/api";

export class ApiError extends Error {
  /**
   * @param {string} message 可直接展示给用户的中文消息
   * @param {string} code 机器可读错误码
   * @param {number} status HTTP 状态码（0 表示网络/超时）
   */
  constructor(message, code = "UNKNOWN_ERROR", status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request(path, options = {}) {
  const { method = "GET", body, query, timeout = 95000 } = options;
  const url = new URL(`${API_ROOT}${path}`, window.location.origin);

  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    });
  }

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url.toString(), {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const raw = await response.text();
    let payload = null;
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        // 非 JSON 通常是代理或服务器层错误，下面统一转换成友好提示。
      }
    }

    if (!response.ok) {
      throw new ApiError(
        payload?.error?.message || "她那边似乎出了点小状况，请稍后再试。",
        payload?.error?.code || "HTTP_ERROR",
        response.status
      );
    }

    if (!payload || payload.ok !== true) {
      throw new ApiError(
        payload?.error?.message || "返回的数据有些奇怪，请刷新后重试。",
        payload?.error?.code || "INVALID_RESPONSE",
        response.status
      );
    }

    return payload.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.name === "AbortError") {
      throw new ApiError("等得有一点久，她可能没听清。再试一次吧。", "TIMEOUT", 0);
    }
    throw new ApiError("网络好像断了，检查一下连接再试。", "NETWORK_ERROR", 0);
  } finally {
    window.clearTimeout(timer);
  }
}

export const api = {
  // ---------- 登录 / 注册 ----------
  getMe() {
    return request("/auth/me", { timeout: 12000 });
  },

  register(username, email, password) {
    return request("/auth/register", {
      method: "POST",
      body: { username, email, password },
      timeout: 20000,
    });
  },

  login(username, password) {
    return request("/auth/login", {
      method: "POST",
      body: { username, password },
      timeout: 20000,
    });
  },

  logout() {
    return request("/auth/logout", {
      method: "POST",
      timeout: 12000,
    });
  },

  // ---------- 人设 / 历史 ----------
  getRecentPersona() {
    return request("/chat/recent", { timeout: 12000 });
  },

  getHistory(girlName, girlChar) {
    return request("/history", {
      query: { girl_name: girlName, girl_char: girlChar },
      timeout: 20000,
    });
  },

  // ---------- 聊天 ----------
  sendMessage(girlName, girlChar, message) {
    return request("/chat", {
      method: "POST",
      body: {
        girl_name: girlName,
        girl_char: girlChar,
        message,
      },
      timeout: 95000,
    });
  },

  // ---------- 状态 ----------
  getHealth() {
    return request("/health", { timeout: 8000 });
  },
};
