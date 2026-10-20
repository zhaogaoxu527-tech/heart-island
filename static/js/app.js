/**
 * 心屿 · AI 女友（账号登录版）
 *
 * 页面流转：
 *   login / register → personality → name → chat
 *
 * 数据规则：
 * - 登录状态由 Flask 服务端 session 维护；
 * - 进入聊天时按「当前登录用户名 + 女友名 + 性别标签」加载 chat_history；
 * - 三者任一变化，都访问另一套独立的历史记录；
 * - 每一轮用户消息与 AI 回复由后端写入 SQLite。
 */

import { api, ApiError } from "./api.js";

// ---------------------------------------------------------------------------
// 静态人设展示配置（与后端 services/persona_service.py 保持一致）
// ---------------------------------------------------------------------------
const PERSONALITIES = {
  gentle: {
    code: "gentle",
    label: "温柔",
    english: "warm",
    icon: "gentle",
    tagline: "把晚风读成情书",
    quote: "“今天也辛苦了，靠过来一点，不用急着说话。”",
    letter:
      "她像一盏留在窗边的暖灯。不会追问你为何晚归，只会把汤重新热一遍，然后安静地听你讲完这一天。",
  },
  grumpy: {
    code: "grumpy",
    label: "暴躁",
    english: "spiky",
    icon: "grumpy",
    tagline: "嘴硬，但心是软的",
    quote: "“气死我了……你吃饭了没？别以为我在关心你。”",
    letter:
      "她讲话像夏天骤雨，落下来时噼里啪啦。可雨停得也快，最后总会别扭地递来一把伞，嘴硬说是顺手带的。",
  },
  sharp: {
    code: "sharp",
    label: "犀利",
    english: "clear",
    icon: "sharp",
    tagline: "清醒地偏爱你",
    quote: "“别绕弯子了，说重点——我在听。”",
    letter:
      "她不太相信漂亮话，却愿意为你在理性的边界上留一个例外。她会在你自欺时戳破，也会在你撑不住时，先替你接住现实。",
  },
};

const FALLBACK_PERSONALITY = {
  code: "gentle",
  label: "她",
  english: "",
  icon: "gentle",
  tagline: "只属于你的她",
  quote: "",
  letter: "",
};

const NAME_SUGGESTIONS = [
  "小满",
  "晚晚",
  "阿梨",
  "星野",
  "南栀",
  "初七",
  "月见",
  "桃桃",
  "知夏",
  "软软",
  "听澜",
  "拾一",
];

const MAX_MESSAGE_LENGTH = 2000;
const SCREEN_ORDER = ["login", "register", "personality", "name", "chat"];
const PROTECTED_SCREENS = new Set(["personality", "name", "chat"]);

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const el = {
  bootScreen: $("bootScreen"),
  screens: [...document.querySelectorAll(".screen")],
  steps: [...document.querySelectorAll(".step")],
  accountChip: $("accountChip"),
  accountAvatar: $("accountAvatar"),
  accountName: $("accountName"),
  headerLogout: $("headerLogout"),
  headerTools: document.querySelector(".header-tools"),
  brandHome: $("brandHome"),

  authTargets: [...document.querySelectorAll("[data-auth-target]")],
  loginForm: $("loginForm"),
  loginUsername: $("loginUsername"),
  loginPassword: $("loginPassword"),
  loginError: $("loginError"),
  loginSubmit: $("loginSubmit"),
  registerForm: $("registerForm"),
  registerUsername: $("registerUsername"),
  registerEmail: $("registerEmail"),
  registerPassword: $("registerPassword"),
  registerConfirm: $("registerConfirm"),
  registerError: $("registerError"),
  registerSubmit: $("registerSubmit"),

  cards: [...document.querySelectorAll(".persona-card")],
  choiceHint: $("choiceHint"),
  nextButton: $("nextButton"),
  continueCard: $("continueCard"),
  continueButton: $("continueButton"),
  continueAvatar: $("continueAvatar"),
  continueName: $("continueName"),
  continueMeta: $("continueMeta"),
  portraitCard: $("portraitCard"),
  portraitArt: $("portraitArt"),
  portraitIcon: $("portraitIcon"),
  selectedLabel: $("selectedLabel"),
  selectedTagline: $("selectedTagline"),
  selectedLetter: $("selectedLetter"),
  backToPersonality: $("backToPersonality"),
  backButton: $("backButton"),
  nameForm: $("nameForm"),
  nameInput: $("girlName"),
  nameInputRow: document.querySelector(".name-input-row"),
  nameCounter: $("nameCounter"),
  nameError: $("nameError"),
  randomName: $("randomName"),
  confirmButton: $("confirmButton"),
  saveNote: $("saveNote"),

  chatAside: $("chatAside"),
  chatMain: document.querySelector(".chat-main"),
  asideBackdrop: $("asideBackdrop"),
  openAside: $("openAside"),
  closeAside: $("closeAside"),
  switchPersona: $("switchPersona"),
  asideLogout: $("asideLogout"),
  asideFace: $("asideFace"),
  asideIcon: $("asideIcon"),
  asideName: $("asideName"),
  asidePersonality: $("asidePersonality"),
  asideQuote: $("asideQuote"),
  asideUsername: $("asideUsername"),
  messageStat: $("messageStat"),
  chatScroll: $("chatScroll"),
  messageList: $("messageList"),
  historyLoader: $("historyLoader"),
  historyHint: $("historyHint"),
  typingIndicator: $("typingIndicator"),
  typingAvatar: $("typingAvatar"),
  typingName: $("typingName"),
  messageInput: $("messageInput"),
  messageCount: $("messageCount"),
  sendButton: $("sendButton"),
  composer: $("composer"),
  promptChips: $("promptChips"),
  scrollDown: $("scrollDown"),
  headerAvatar: $("headerAvatar"),
  chatName: $("chatName"),
  chatStatus: $("chatStatus"),
  modeBadge: $("modeBadge"),
  modeBadgeText: $("modeBadgeText"),
  replyMode: $("replyMode"),

  confirmDialog: $("confirmDialog"),
  dialogTitle: $("dialogTitle"),
  dialogMessage: $("dialogMessage"),
  dialogCancel: $("dialogCancel"),
  dialogConfirm: $("dialogConfirm"),
  toastRegion: $("toastRegion"),
};

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const mobileAsideQuery = window.matchMedia("(max-width: 980px)");
const finePointerQuery = window.matchMedia("(pointer: fine)");

// ---------------------------------------------------------------------------
// 状态
// ---------------------------------------------------------------------------
const state = {
  screen: "login",
  authenticated: false,
  user: null,
  selectedPersonality: null,
  savedPersona: null,
  persona: null,
  messages: [],
  visibleCount: 30,
  loadingHistory: false,
  loadingOlder: false,
  sending: false,
  nameTouched: false,
  isComposing: false,
  dialogResolver: null,
  llmMode: "loading",
  llmModel: null,
};

// ---------------------------------------------------------------------------
// 通用工具
// ---------------------------------------------------------------------------
function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function getPersonality(code) {
  return PERSONALITIES[code] || FALLBACK_PERSONALITY;
}

function getPersonalityByLabel(label) {
  return Object.values(PERSONALITIES).find((preset) => preset.label === label) || null;
}

function safeIcon(name) {
  const allowed = new Set([
    "gentle",
    "grumpy",
    "sharp",
    "arrow-right",
    "arrow-left",
    "check",
    "menu",
    "close",
    "refresh",
    "lock",
    "heart",
    "send",
    "sparkles",
    "message",
    "shuffle",
    "chevron-down",
    "logout",
  ]);
  return allowed.has(name) ? name : "gentle";
}

function iconMarkup(name, className = "avatar-icon") {
  return `<svg class="${className}" aria-hidden="true"><use href="#icon-${safeIcon(name)}"></use></svg>`;
}

function createIcon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${safeIcon(name)}`);
  svg.appendChild(use);
  return svg;
}

function setAvatar(element, personalityCode) {
  if (!element) return;
  const preset = getPersonality(personalityCode);
  element.dataset.personality = preset.code;
  element.innerHTML = iconMarkup(preset.icon);
}

function setAsideIcon(personalityCode) {
  const preset = getPersonality(personalityCode);
  el.asideFace.dataset.personality = preset.code;
  el.asideIcon.innerHTML = `<use href="#icon-${safeIcon(preset.icon)}"></use>`;
}

function showToast(message, { tone = "default", duration = 3600 } = {}) {
  if (!message) return;
  const toast = document.createElement("div");
  toast.className = `toast${tone === "error" ? " is-error" : ""}`;
  toast.setAttribute("role", tone === "error" ? "alert" : "status");
  toast.appendChild(createIcon(tone === "error" ? "close" : "heart", "icon"));
  const text = document.createElement("span");
  text.textContent = message;
  toast.appendChild(text);

  el.toastRegion.appendChild(toast);
  while (el.toastRegion.children.length > 3) {
    el.toastRegion.firstElementChild?.remove();
  }

  window.setTimeout(() => {
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 300);
  }, duration);
}

function setButtonLoading(button, loading, label = "请稍候") {
  if (loading) {
    if (!button.dataset.originalHtml) {
      button.dataset.originalHtml = button.innerHTML;
    }
    button.classList.add("is-loading");
    button.disabled = true;
    button.replaceChildren();
    const spinner = document.createElement("span");
    spinner.className = "button-spinner";
    spinner.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.textContent = label;
    button.append(spinner, text);
  } else {
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
      delete button.dataset.originalHtml;
    }
    button.classList.remove("is-loading");
    button.disabled = false;
  }
}

function askConfirm({
  title,
  message,
  confirmText = "确认",
  cancelText = "再想想",
  danger = false,
}) {
  if (typeof el.confirmDialog.showModal !== "function") {
    return Promise.resolve(window.confirm(`${title}\n\n${message}`));
  }
  el.dialogTitle.textContent = title;
  el.dialogMessage.textContent = message;
  el.dialogConfirm.textContent = confirmText;
  el.dialogCancel.textContent = cancelText;
  el.dialogConfirm.classList.toggle("is-danger", danger);
  return new Promise((resolve) => {
    state.dialogResolver = resolve;
    el.confirmDialog.showModal();
    el.dialogConfirm.focus();
  });
}

function finishDialog(result) {
  if (!el.confirmDialog.open) return;
  el.confirmDialog.close();
  const resolve = state.dialogResolver;
  state.dialogResolver = null;
  resolve?.(result);
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTime(value) {
  const date = parseDate(value);
  if (!date) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function dayKey(date) {
  if (!date) return "";
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function dayLabel(date) {
  if (!date) return "";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfThatDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((startOfToday - startOfThatDay) / 86400000);
  if (diffDays === 0) return "今天";
  if (diffDays === 1) return "昨天";
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  }
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

function updateChoiceHint(text, selected = false) {
  el.choiceHint.replaceChildren();
  const dot = document.createElement("span");
  dot.setAttribute("aria-hidden", "true");
  el.choiceHint.append(dot, document.createTextNode(text));
  el.choiceHint.classList.toggle("has-selection", selected);
}

function hideBootScreen() {
  if (!el.bootScreen) return;
  el.bootScreen.classList.add("is-hidden");
  window.setTimeout(() => {
    el.bootScreen.hidden = true;
  }, 650);
}

// ---------------------------------------------------------------------------
// 页面切换与账号状态
// ---------------------------------------------------------------------------
function setAuthenticatedUser(user) {
  state.user = user;
  state.authenticated = Boolean(user);
  document.body.dataset.authenticated = String(state.authenticated);
  el.accountChip.hidden = !state.authenticated;

  if (user) {
    const initial = Array.from(user.username || "你")[0];
    el.accountAvatar.textContent = initial;
    el.accountName.textContent = user.username;
    el.asideUsername.textContent = user.username;
  } else {
    el.accountAvatar.textContent = "你";
    el.accountName.textContent = "账号";
    el.asideUsername.textContent = "—";
  }
}

function updateDocumentTitle() {
  if (state.screen === "login") {
    document.title = "登录 · 心屿";
  } else if (state.screen === "register") {
    document.title = "注册 · 心屿";
  } else if (state.screen === "name") {
    document.title = "为她命名 · 心屿";
  } else if (state.screen === "chat" && state.persona) {
    document.title = `${state.persona.name} · 心屿`;
  } else {
    document.title = "心屿 · AI 女友";
  }
}

function goToScreen(screen) {
  if (!SCREEN_ORDER.includes(screen)) return;
  if (!state.authenticated && PROTECTED_SCREENS.has(screen)) {
    screen = "login";
  }
  state.screen = screen;
  document.body.dataset.screen = screen;

  el.screens.forEach((section) => {
    const active = section.dataset.screen === screen;
    section.hidden = !active;
    section.classList.toggle("is-active", active);
  });

  const currentIndex = SCREEN_ORDER.indexOf(screen);
  el.steps.forEach((step) => {
    const index = SCREEN_ORDER.indexOf(step.dataset.step);
    step.classList.toggle("is-current", index === currentIndex);
    step.classList.toggle("is-done", index < currentIndex);
    if (index === currentIndex) {
      step.setAttribute("aria-current", "step");
    } else {
      step.removeAttribute("aria-current");
    }
  });

  updateDocumentTitle();

  if (screen === "chat") {
    closeAside({ restoreFocus: false });
  } else {
    closeAside({ restoreFocus: false });
    window.scrollTo({
      top: 0,
      behavior: prefersReducedMotion.matches ? "auto" : "smooth",
    });
  }

  if (screen === "login" || screen === "register") {
    window.setTimeout(() => {
      const input =
        screen === "login" ? el.loginUsername : el.registerUsername;
      if (input && !input.disabled) input.focus({ preventScroll: true });
    }, prefersReducedMotion.matches ? 0 : 280);
  }
}

function resetWorkspace() {
  state.selectedPersonality = null;
  state.savedPersona = null;
  state.persona = null;
  state.messages = [];
  state.visibleCount = 30;
  state.loadingHistory = false;
  state.loadingOlder = false;
  state.sending = false;
  state.nameTouched = false;
  state.llmMode = "loading";
  state.llmModel = null;

  el.cards.forEach((card) => card.setAttribute("aria-pressed", "false"));
  el.nextButton.disabled = true;
  updateChoiceHint("先选一个让你心动的她", false);
  el.continueCard.hidden = true;
  el.nameInput.value = "";
  validateName();
  el.messageInput.value = "";
  updateSendAvailability();
  el.messageStat.textContent = "已经收藏了 0 条悄悄话";
  el.modeBadge.classList.remove("is-api", "is-error");
  el.modeBadgeText.textContent = "等待登录";
}

function handleAuthExpired() {
  setAuthenticatedUser(null);
  resetWorkspace();
  goToScreen("login");
  showToast("登录状态已失效，请重新登录。", { tone: "error", duration: 4600 });
}

function handleApiError(error) {
  // 只有已经登录的会话过期才触发强制退出；
  // 登录页输错密码返回 401 时应该留在表单里展示错误。
  if (error instanceof ApiError && error.status === 401 && state.authenticated) {
    handleAuthExpired();
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// 登录 / 注册
// ---------------------------------------------------------------------------
function setAuthError(target, message) {
  const node = target === "register" ? el.registerError : el.loginError;
  node.textContent = message || "";
}

function switchAuthScreen(target) {
  if (target !== "login" && target !== "register") return;
  setAuthError("login", "");
  setAuthError("register", "");
  goToScreen(target);
}

function validateRegister() {
  const username = el.registerUsername.value.trim();
  const email = el.registerEmail.value.trim();
  const password = el.registerPassword.value;
  const confirm = el.registerConfirm.value;

  if (!/^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$/.test(username)) {
    return "用户名需要 3–20 个字符，只能包含中文、字母、数字和下划线。";
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return "请输入有效的邮箱地址。";
  }
  if (password.length < 6) {
    return "密码至少需要 6 位。";
  }
  if (password !== confirm) {
    return "两次输入的密码不一致。";
  }
  return "";
}

async function handleLogin(event) {
  event.preventDefault();
  setAuthError("login", "");
  const username = el.loginUsername.value.trim();
  const password = el.loginPassword.value;
  if (!username || !password) {
    setAuthError("login", "请输入用户名和密码。");
    return;
  }

  setButtonLoading(el.loginSubmit, true, "正在推门…");
  el.loginUsername.disabled = true;
  el.loginPassword.disabled = true;

  try {
    const data = await api.login(username, password);
    setAuthenticatedUser(data.user);
    await Promise.allSettled([refreshHealth(), loadRecentPersona()]);
    goToScreen("personality");
    showToast(`欢迎回来，${data.user.username}。`, { duration: 3000 });
  } catch (error) {
    if (!handleApiError(error)) {
      setAuthError(
        "login",
        error instanceof ApiError ? error.message : "登录失败，请稍后再试。"
      );
    }
  } finally {
    el.loginUsername.disabled = false;
    el.loginPassword.disabled = false;
    setButtonLoading(el.loginSubmit, false);
  }
}

async function handleRegister(event) {
  event.preventDefault();
  setAuthError("register", "");
  const error = validateRegister();
  if (error) {
    setAuthError("register", error);
    return;
  }

  const username = el.registerUsername.value.trim();
  const email = el.registerEmail.value.trim();
  const password = el.registerPassword.value;

  setButtonLoading(el.registerSubmit, true, "正在点灯…");
  for (const input of [
    el.registerUsername,
    el.registerEmail,
    el.registerPassword,
    el.registerConfirm,
  ]) {
    input.disabled = true;
  }

  try {
    await api.register(username, email, password);
    el.registerPassword.value = "";
    el.registerConfirm.value = "";
    el.loginUsername.value = username;
    el.loginPassword.value = "";
    goToScreen("login");
    setAuthError("login", "");
    showToast("账号已经建好了，用刚才的密码登录吧。", { duration: 4200 });
    window.setTimeout(() => {
      el.loginPassword.focus({ preventScroll: true });
    }, prefersReducedMotion.matches ? 0 : 300);
  } catch (error) {
    if (!handleApiError(error)) {
      setAuthError(
        "register",
        error instanceof ApiError ? error.message : "注册失败，请稍后再试。"
      );
    }
  } finally {
    for (const input of [
      el.registerUsername,
      el.registerEmail,
      el.registerPassword,
      el.registerConfirm,
    ]) {
      input.disabled = false;
    }
    setButtonLoading(el.registerSubmit, false);
  }
}

async function logout() {
  if (state.sending) {
    showToast("等她把这句说完，再离开吧。", { duration: 2800 });
    return;
  }
  const confirmed = await askConfirm({
    title: "要离开这座岛吗？",
    message: "账号和聊天记录会留在 SQLite 中。下次用同一个账号登录，还能接着聊。",
    confirmText: "退出登录",
  });
  if (!confirmed) return;

  try {
    await api.logout();
    setAuthenticatedUser(null);
    resetWorkspace();
    goToScreen("login");
    el.loginPassword.value = "";
    showToast("门已经关好了。下次再来找她。", { duration: 3200 });
  } catch (error) {
    if (!handleApiError(error)) {
      showToast(
        error instanceof ApiError ? error.message : "退出失败，请稍后再试。",
        { tone: "error" }
      );
    }
  }
}

async function bootstrapAuth() {
  try {
    const data = await api.getMe();
    if (data.authenticated) {
      setAuthenticatedUser(data.user);
      await Promise.allSettled([refreshHealth(), loadRecentPersona()]);
      goToScreen("personality");
    } else {
      setAuthenticatedUser(null);
      goToScreen("login");
    }
  } catch (error) {
    setAuthenticatedUser(null);
    goToScreen("login");
    showToast(
      error instanceof ApiError
        ? `暂时无法确认登录状态：${error.message}`
        : "暂时无法连接服务，请稍后刷新。",
      { tone: "error", duration: 5000 }
    );
  }
}

// ---------------------------------------------------------------------------
// 首页 / 最近对话
// ---------------------------------------------------------------------------
function renderContinueCard() {
  const persona = state.savedPersona;
  if (!persona) {
    el.continueCard.hidden = true;
    return;
  }
  const code =
    persona.personality ||
    getPersonalityByLabel(persona.girl_char)?.code ||
    "gentle";
  setAvatar(el.continueAvatar, code);
  el.continueName.textContent = persona.girl_name;
  el.continueMeta.textContent = `${persona.girl_char} · 已收藏 ${
    persona.message_count || 0
  } 条对话`;
  el.continueCard.hidden = false;
}

async function loadRecentPersona() {
  state.savedPersona = null;
  if (!state.authenticated) {
    renderContinueCard();
    return;
  }
  try {
    const data = await api.getRecentPersona();
    state.savedPersona = data?.persona || null;
  } catch (error) {
    if (!handleApiError(error)) {
      console.warn("读取最近对话失败：", error);
    }
    state.savedPersona = null;
  }
  renderContinueCard();
}

async function resumeRecentPersona() {
  const recent = state.savedPersona;
  if (!recent) return;
  const code =
    recent.personality ||
    getPersonalityByLabel(recent.girl_char)?.code ||
    "gentle";
  const preset = getPersonality(code);
  state.selectedPersonality = code;
  await beginChat({
    name: recent.girl_name,
    label: recent.girl_char || preset.label,
    code,
  });
}

// ---------------------------------------------------------------------------
// 性格选择
// ---------------------------------------------------------------------------
function updatePersonalityPreview(code) {
  const preset = getPersonality(code);
  el.portraitCard.dataset.personality = preset.code;
  el.portraitArt.dataset.personality = preset.code;
  el.portraitIcon.innerHTML = `<use href="#icon-${safeIcon(preset.icon)}"></use>`;
  el.selectedLabel.textContent = preset.label;
  el.selectedTagline.textContent = preset.tagline;
  el.selectedLetter.textContent = preset.letter || preset.quote;
}

function selectPersonality(code) {
  const preset = PERSONALITIES[code];
  if (!preset) return;
  state.selectedPersonality = code;
  el.cards.forEach((card) => {
    card.setAttribute(
      "aria-pressed",
      String(card.dataset.personality === code)
    );
  });
  el.nextButton.disabled = false;
  updateChoiceHint(`已选择「${preset.label}」 · 下一步为她取个名字`, true);
  updatePersonalityPreview(code);
}

function prepareNameScreen() {
  if (!state.selectedPersonality) {
    updateChoiceHint("先选一个让你心动的她", false);
    return;
  }
  updatePersonalityPreview(state.selectedPersonality);
  state.nameTouched = false;
  validateName();
  goToScreen("name");
  window.setTimeout(
    () => el.nameInput.focus({ preventScroll: true }),
    prefersReducedMotion.matches ? 0 : 320
  );
}

// ---------------------------------------------------------------------------
// 命名与进入聊天
// ---------------------------------------------------------------------------
function validateName() {
  const raw = el.nameInput.value;
  const name = raw.replace(/\s+/g, " ").trim();
  const length = Array.from(name).length;
  let message = "";
  let valid = true;

  el.nameCounter.textContent = `${Array.from(raw).length} / 10`;

  if (state.nameTouched) {
    if (!name) {
      message = "名字不能为空，哪怕只是一个昵称也好。";
      valid = false;
    } else if (length > 10) {
      message = "名字最多 10 个字，短一点更容易被记住。";
      valid = false;
    } else if (/[<>{}\r\n\t`]/.test(name)) {
      message = "名字里包含不支持的符号，换一个试试吧。";
      valid = false;
    }
  }

  el.nameError.textContent = message;
  el.nameInputRow.classList.toggle("is-invalid", Boolean(message));
  el.nameInput.setAttribute("aria-invalid", String(Boolean(message)));
  el.confirmButton.disabled =
    !valid || !name || !state.selectedPersonality || state.sending;
  return { valid: valid && Boolean(name), name };
}

function fillSuggestedName(name) {
  el.nameInput.value = name;
  state.nameTouched = true;
  validateName();
  el.nameInput.focus({ preventScroll: true });
  el.nameInput.setSelectionRange(name.length, name.length);
}

function pickRandomName() {
  const current = el.nameInput.value.trim();
  const pool = NAME_SUGGESTIONS.filter((name) => name !== current);
  fillSuggestedName(pool[Math.floor(Math.random() * pool.length)]);
}

async function handleNameSubmit(event) {
  event.preventDefault();
  if (!state.authenticated) {
    handleAuthExpired();
    return;
  }
  if (!state.selectedPersonality) {
    showToast("先选一位她的性格吧。", { tone: "error" });
    goToScreen("personality");
    return;
  }
  state.nameTouched = true;
  const result = validateName();
  if (!result.valid) {
    el.nameInput.focus({ preventScroll: true });
    return;
  }

  const preset = getPersonality(state.selectedPersonality);
  await beginChat({
    name: result.name,
    label: preset.label,
    code: preset.code,
  });
}

async function beginChat(persona) {
  state.persona = {
    name: persona.name,
    label: persona.label,
    code: persona.code,
  };
  state.messages = [];
  state.visibleCount = 30;
  state.loadingHistory = false;
  state.loadingOlder = false;
  configureChatUI();
  goToScreen("chat");
  await loadChatHistory();
}

// ---------------------------------------------------------------------------
// 聊天历史与消息渲染
// ---------------------------------------------------------------------------
function configureChatUI() {
  const persona = state.persona;
  if (!persona) return;
  const preset = getPersonality(persona.code);
  el.chatName.textContent = persona.name;
  el.asideName.textContent = persona.name;
  el.typingName.textContent = persona.name;
  el.asidePersonality.textContent = `${persona.label} · ${preset.english}`;
  el.asideQuote.textContent = preset.quote;
  el.asideUsername.textContent = state.user?.username || "—";
  setAvatar(el.headerAvatar, persona.code);
  setAvatar(el.typingAvatar, persona.code);
  setAsideIcon(persona.code);
  updateDocumentTitle();
  updateModeUI();
  updateMessageStats();
  updatePromptChips();
  syncAsideAccessibility();
}

function updateModeUI() {
  el.modeBadge.classList.remove("is-api", "is-error");
  el.chatStatus.textContent = "在你身边";

  if (state.llmMode === "kimi") {
    el.modeBadge.classList.add("is-api");
    el.modeBadgeText.textContent = "Kimi";
    el.replyMode.textContent = `${state.llmModel || "kimi"} · 服务端组装人设与历史`;
    el.chatStatus.textContent = "在线 · 正在等你";
  } else if (state.llmMode === "fallback") {
    el.modeBadge.classList.add("is-error");
    el.modeBadgeText.textContent = "本地回退";
    el.replyMode.textContent = "Kimi 暂不可用，正在用内置角色回复";
    el.chatStatus.textContent = "信号有点弱";
  } else if (state.llmMode === "demo") {
    el.modeBadgeText.textContent = "本地体验";
    el.replyMode.textContent = "本地体验 · 未配置 Kimi 密钥";
    el.chatStatus.textContent = "在你身边";
  } else if (state.llmMode === "offline") {
    el.modeBadge.classList.add("is-error");
    el.modeBadgeText.textContent = "连接中断";
    el.replyMode.textContent = "暂时无法确认模型状态，发送时会再试一次";
    el.chatStatus.textContent = "信号有点弱";
  } else {
    el.modeBadgeText.textContent = "连接中";
    el.replyMode.textContent = "正在确认她的状态…";
    el.chatStatus.textContent = "正在靠近…";
  }
}

function updatePresence(typing) {
  if (!state.persona) return;
  if (typing) {
    el.chatStatus.textContent = "正在输入…";
    return;
  }
  if (state.llmMode === "fallback" || state.llmMode === "offline") {
    el.chatStatus.textContent = "信号有点弱";
  } else if (state.llmMode === "kimi") {
    el.chatStatus.textContent = "在线 · 正在等你";
  } else {
    el.chatStatus.textContent = "在你身边";
  }
}

function updateMessageStats() {
  const count = state.messages.length;
  el.messageStat.textContent =
    count > 0 ? `已经收藏了 ${count} 条悄悄话` : "第一句话，正等着你开口";
  if (state.persona && state.savedPersona) {
    if (
      state.savedPersona.girl_name === state.persona.name &&
      state.savedPersona.girl_char === state.persona.label
    ) {
      state.savedPersona.message_count = count;
      renderContinueCard();
    }
  }
}

function updatePromptChips() {
  const hasUserMessage = state.messages.some((message) => message.role === "user");
  el.promptChips.hidden = hasUserMessage || state.sending;
}

function updateSendAvailability() {
  const hasText = el.messageInput.value.trim().length > 0;
  el.sendButton.disabled = !hasText || state.sending;
  el.messageInput.disabled = state.sending;
  if (state.sending) {
    el.messageInput.setAttribute("aria-busy", "true");
  } else {
    el.messageInput.removeAttribute("aria-busy");
  }
  const length = Array.from(el.messageInput.value).length;
  el.messageCount.textContent =
    length > 1500 ? `${length} / ${MAX_MESSAGE_LENGTH}` : "";
}

function autoResizeTextarea() {
  el.messageInput.style.height = "auto";
  const next = Math.min(el.messageInput.scrollHeight, 140);
  el.messageInput.style.height = `${Math.max(next, 42)}px`;
}

function showTyping(visible) {
  el.typingIndicator.hidden = !visible;
  updatePresence(visible);
  if (visible) scrollToBottom(true);
}

function scrollToBottom(smooth = false) {
  const behavior = smooth && !prefersReducedMotion.matches ? "smooth" : "auto";
  window.requestAnimationFrame(() => {
    el.chatScroll.scrollTo({ top: el.chatScroll.scrollHeight, behavior });
  });
}

function updateScrollDownVisibility() {
  const distance =
    el.chatScroll.scrollHeight -
    el.chatScroll.scrollTop -
    el.chatScroll.clientHeight;
  el.scrollDown.hidden = distance < 360;
}

function hasOlderMessages() {
  return state.messages.length > state.visibleCount;
}

function updateHistoryUI() {
  el.historyLoader.hidden = !state.loadingOlder;
  el.historyHint.hidden =
    !hasOlderMessages() || state.loadingOlder || state.loadingHistory;
}

function visibleMessages() {
  const count = Math.min(state.visibleCount, state.messages.length);
  return state.messages.slice(-count);
}

function createDayDivider(date) {
  const divider = document.createElement("div");
  divider.className = "day-divider";
  divider.textContent = dayLabel(date);
  return divider;
}

function createMessageNode(message, isNew) {
  const isUser = message.role === "user";
  const article = document.createElement("article");
  article.className = `message ${isUser ? "message-user" : "message-assistant"}${
    isNew ? " is-new" : ""
  }`;
  article.dataset.messageId = String(message.id);

  const avatar = document.createElement("div");
  avatar.setAttribute("aria-hidden", "true");
  if (isUser) {
    avatar.className = "avatar avatar-user";
    avatar.textContent = "你";
  } else {
    avatar.className = "avatar avatar-ai";
    setAvatar(avatar, state.persona?.code);
  }

  const content = document.createElement("div");
  content.className = "message-content";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const name = document.createElement("strong");
  name.textContent = isUser ? "你" : state.persona?.name || "她";
  const time = document.createElement("time");
  const timeValue = message.create_time || message.created_at;
  const date = parseDate(timeValue);
  if (date) {
    time.dateTime = date.toISOString();
    time.textContent = formatTime(timeValue);
  }
  meta.append(name, time);

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = message.content;
  content.append(meta, bubble);
  article.append(avatar, content);
  return article;
}

function renderMessages({ animateIds = [] } = {}) {
  const fragment = document.createDocumentFragment();
  const animateSet = new Set(animateIds.map(String));
  let currentDay = "";
  const messages = visibleMessages();

  messages.forEach((message) => {
    const date = parseDate(message.create_time || message.created_at);
    const key = dayKey(date);
    if (key && key !== currentDay) {
      currentDay = key;
      fragment.appendChild(createDayDivider(date));
    }
    fragment.appendChild(createMessageNode(message, animateSet.has(String(message.id))));
  });

  if (messages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "chat-state";
    empty.append(
      createIcon("message", "icon"),
      Object.assign(document.createElement("p"), {
        className: "chat-state-title",
        textContent: `${state.persona?.name || "她"}还在等你的第一句话`,
      }),
      Object.assign(document.createElement("p"), {
        textContent: "同一账号、同一名字与性格，下次回来还会接上这段对话。",
      })
    );
    fragment.appendChild(empty);
  }

  el.messageList.replaceChildren(fragment);
}

function showChatSkeleton() {
  const wrapper = document.createElement("div");
  wrapper.className = "chat-loading";
  wrapper.setAttribute("aria-hidden", "true");
  [false, true, false].forEach((isUser) => {
    const row = document.createElement("div");
    row.className = `skeleton-row${isUser ? " is-user" : ""}`;
    const avatar = document.createElement("span");
    avatar.className = "skeleton-avatar";
    const bubble = document.createElement("span");
    bubble.className = "skeleton-bubble";
    row.append(avatar, bubble);
    wrapper.appendChild(row);
  });
  el.messageList.replaceChildren(wrapper);
}

function renderChatError(message, retryLabel = "再试一次", onRetry = loadChatHistory) {
  const wrapper = document.createElement("div");
  wrapper.className = "chat-state";
  wrapper.append(createIcon("message", "icon"));
  const title = document.createElement("p");
  title.className = "chat-state-title";
  title.textContent = "这些话暂时没有取回来";
  const detail = document.createElement("p");
  detail.textContent = message;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "btn btn-ghost";
  retry.textContent = retryLabel;
  retry.addEventListener("click", onRetry);
  wrapper.append(title, detail, retry);
  el.messageList.replaceChildren(wrapper);
}

async function loadChatHistory() {
  if (!state.authenticated || !state.persona) return;
  if (state.loadingHistory) return;
  state.loadingHistory = true;
  state.messages = [];
  state.visibleCount = 30;
  el.historyLoader.hidden = true;
  el.historyHint.hidden = true;
  el.messageList.setAttribute("aria-busy", "true");
  showChatSkeleton();
  updateMessageStats();

  try {
    const data = await api.getHistory(state.persona.name, state.persona.label);
    state.messages = Array.isArray(data.items) ? data.items : [];
    // 需求要求直接恢复该套配置下的全部历史记录，因此一次性渲染全部。
    state.visibleCount = state.messages.length;
    renderMessages();
    updateMessageStats();
    updateHistoryUI();
    updatePromptChips();
    scrollToBottom(false);
    updateScrollDownVisibility();
  } catch (error) {
    if (handleApiError(error)) return;
    const message =
      error instanceof ApiError ? error.message : "历史记录暂时没有加载成功。";
    renderChatError(message);
    showToast(message, { tone: "error", duration: 5000 });
  } finally {
    state.loadingHistory = false;
    el.messageList.setAttribute("aria-busy", "false");
    updateHistoryUI();
  }
}

async function loadOlderMessages() {
  if (
    state.loadingOlder ||
    state.loadingHistory ||
    state.sending ||
    !hasOlderMessages()
  ) {
    return;
  }
  state.loadingOlder = true;
  el.historyLoader.hidden = false;
  el.historyHint.hidden = true;
  const previousHeight = el.chatScroll.scrollHeight;
  const previousTop = el.chatScroll.scrollTop;
  await delay(180);
  state.visibleCount = Math.min(state.visibleCount + 24, state.messages.length);
  renderMessages();
  el.chatScroll.scrollTop =
    el.chatScroll.scrollHeight - previousHeight + previousTop;
  state.loadingOlder = false;
  updateHistoryUI();
}

// ---------------------------------------------------------------------------
// 模型状态
// ---------------------------------------------------------------------------
async function refreshHealth() {
  try {
    const data = await api.getHealth();
    state.llmMode = data?.llm?.mode || "demo";
    state.llmModel = data?.llm?.model || null;
    updateModeUI();
  } catch (error) {
    state.llmMode = "offline";
    updateModeUI();
  }
}

// ---------------------------------------------------------------------------
// 发送消息
// ---------------------------------------------------------------------------
async function sendCurrentMessage() {
  if (state.sending || !state.persona || !state.authenticated) return;
  const text = el.messageInput.value.trim();
  if (!text) return;
  if (Array.from(text).length > MAX_MESSAGE_LENGTH) {
    showToast(`单条消息最多 ${MAX_MESSAGE_LENGTH} 个字。`, { tone: "error" });
    return;
  }

  const optimistic = {
    id: `temp-${Date.now()}`,
    role: "user",
    content: text,
    create_time: new Date().toISOString(),
  };

  state.sending = true;
  state.messages = [...state.messages, optimistic];
  el.messageInput.value = "";
  autoResizeTextarea();
  updateSendAvailability();
  updatePromptChips();
  renderMessages({ animateIds: [optimistic.id] });
  scrollToBottom(true);
  showTyping(true);

  try {
    const data = await api.sendMessage(
      state.persona.name,
      state.persona.label,
      text
    );
    state.messages = state.messages.filter((message) => message.id !== optimistic.id);
    const knownIds = new Set(state.messages.map((message) => String(message.id)));
    const incoming = [data.user_message, data.assistant_message].filter(
      (message) => message && !knownIds.has(String(message.id))
    );
    state.messages.push(...incoming);
    state.visibleCount = state.messages.length;

    if (data.mode) {
      state.llmMode = data.mode;
      updateModeUI();
    }
    // 刚发过消息的这套人设就是最近的会话，更新首页「继续上次」卡片。
    state.savedPersona = {
      girl_name: state.persona.name,
      girl_char: state.persona.label,
      personality: state.persona.code,
      message_count: state.messages.length,
    };
    renderMessages({ animateIds: incoming.map((message) => message.id) });
    updateMessageStats();
    updateHistoryUI();
    updatePromptChips();
    scrollToBottom(true);
    if (data.notice) {
      showToast(data.notice, { tone: "error", duration: 6000 });
    }
  } catch (error) {
    state.messages = state.messages.filter((message) => message.id !== optimistic.id);
    el.messageInput.value = text;
    autoResizeTextarea();
    renderMessages();
    updatePromptChips();
    if (!handleApiError(error)) {
      showToast(
        error instanceof ApiError ? error.message : "这句话没有送出去，再试一次吧。",
        { tone: "error", duration: 5600 }
      );
    }
  } finally {
    state.sending = false;
    el.typingIndicator.hidden = true;
    updateSendAvailability();
    updatePromptChips();
    updatePresence(false);
    if (finePointerQuery.matches && state.screen === "chat") {
      el.messageInput.focus({ preventScroll: true });
    }
  }
}

// ---------------------------------------------------------------------------
// 侧栏
// ---------------------------------------------------------------------------
function syncAsideAccessibility() {
  if (!el.chatAside || !el.chatMain) return;
  const isMobile = mobileAsideQuery.matches;
  const isOpen = el.chatAside.classList.contains("is-open");
  if (!isMobile) {
    el.chatAside.inert = false;
    el.chatAside.removeAttribute("aria-hidden");
    el.chatMain.inert = false;
    if (isOpen) {
      el.chatAside.classList.remove("is-open");
      el.asideBackdrop.hidden = true;
      document.body.classList.remove("aside-open");
      el.openAside.setAttribute("aria-expanded", "false");
    }
    return;
  }
  el.chatAside.inert = !isOpen;
  if (isOpen) {
    el.chatAside.removeAttribute("aria-hidden");
  } else {
    el.chatAside.setAttribute("aria-hidden", "true");
  }
  el.chatMain.inert = isOpen;
}

function openAside() {
  if (!mobileAsideQuery.matches) return;
  el.chatAside.classList.add("is-open");
  el.asideBackdrop.hidden = false;
  el.openAside.setAttribute("aria-expanded", "true");
  document.body.classList.add("aside-open");
  syncAsideAccessibility();
  window.setTimeout(() => el.closeAside.focus({ preventScroll: true }), 120);
}

function closeAside({ restoreFocus = true } = {}) {
  if (!el.chatAside.classList.contains("is-open")) {
    syncAsideAccessibility();
    return;
  }
  el.chatAside.classList.remove("is-open");
  el.asideBackdrop.hidden = true;
  el.openAside.setAttribute("aria-expanded", "false");
  document.body.classList.remove("aside-open");
  syncAsideAccessibility();
  if (restoreFocus && state.screen === "chat" && mobileAsideQuery.matches) {
    el.openAside.focus({ preventScroll: true });
  }
}

async function switchToPersonaSetup() {
  if (state.sending) {
    showToast("等她把这句说完，再换一位她吧。", { duration: 3000 });
    return;
  }
  closeAside({ restoreFocus: false });
  goToScreen("personality");
  if (state.selectedPersonality) {
    updateChoiceHint("换一位，还是保持原来的选择？", true);
  }
}

// ---------------------------------------------------------------------------
// 事件
// ---------------------------------------------------------------------------
function bindEvents() {
  el.authTargets.forEach((button) => {
    button.addEventListener("click", () => switchAuthScreen(button.dataset.authTarget));
  });

  el.loginForm.addEventListener("submit", handleLogin);
  el.registerForm.addEventListener("submit", handleRegister);
  el.loginUsername.addEventListener("input", () => setAuthError("login", ""));
  el.loginPassword.addEventListener("input", () => setAuthError("login", ""));
  el.registerUsername.addEventListener("input", () => setAuthError("register", ""));
  el.registerEmail.addEventListener("input", () => setAuthError("register", ""));
  el.registerPassword.addEventListener("input", () => setAuthError("register", ""));
  el.registerConfirm.addEventListener("input", () => setAuthError("register", ""));

  el.headerLogout.addEventListener("click", logout);
  el.asideLogout.addEventListener("click", logout);

  el.brandHome.addEventListener("click", () => {
    if (state.authenticated && state.screen !== "personality") {
      goToScreen("personality");
    }
  });

  el.cards.forEach((card) => {
    card.addEventListener("click", () => selectPersonality(card.dataset.personality));
  });
  el.nextButton.addEventListener("click", prepareNameScreen);
  el.backToPersonality.addEventListener("click", () => goToScreen("personality"));
  el.backButton.addEventListener("click", () => goToScreen("personality"));

  el.nameForm.addEventListener("submit", handleNameSubmit);
  el.nameInput.addEventListener("input", () => {
    state.nameTouched = true;
    validateName();
  });
  el.nameInput.addEventListener("blur", () => {
    state.nameTouched = true;
    validateName();
  });
  el.randomName.addEventListener("click", pickRandomName);
  document.querySelectorAll("[data-suggest]").forEach((button) => {
    button.addEventListener("click", () => fillSuggestedName(button.dataset.suggest));
  });

  el.continueButton.addEventListener("click", resumeRecentPersona);

  el.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    sendCurrentMessage();
  });
  el.messageInput.addEventListener("input", () => {
    autoResizeTextarea();
    updateSendAvailability();
  });
  el.messageInput.addEventListener("compositionstart", () => {
    state.isComposing = true;
  });
  el.messageInput.addEventListener("compositionend", () => {
    state.isComposing = false;
  });
  el.messageInput.addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.isComposing &&
      !state.isComposing
    ) {
      event.preventDefault();
      el.composer.requestSubmit();
    }
  });

  el.promptChips.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (!button) return;
    el.messageInput.value = button.dataset.prompt || "";
    autoResizeTextarea();
    updateSendAvailability();
    el.messageInput.focus({ preventScroll: true });
  });

  el.chatScroll.addEventListener("scroll", () => {
    updateScrollDownVisibility();
    if (el.chatScroll.scrollTop < 90) loadOlderMessages();
  });
  el.scrollDown.addEventListener("click", () => scrollToBottom(true));

  el.openAside.addEventListener("click", openAside);
  el.closeAside.addEventListener("click", () => closeAside());
  el.asideBackdrop.addEventListener("click", () => closeAside());
  el.switchPersona.addEventListener("click", switchToPersonaSetup);

  el.dialogCancel.addEventListener("click", () => finishDialog(false));
  el.dialogConfirm.addEventListener("click", () => finishDialog(true));
  el.confirmDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    finishDialog(false);
  });
  el.confirmDialog.addEventListener("close", () => {
    if (state.dialogResolver) {
      const resolve = state.dialogResolver;
      state.dialogResolver = null;
      resolve(false);
    }
  });
  el.confirmDialog.addEventListener("click", (event) => {
    if (event.target === el.confirmDialog) finishDialog(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && el.chatAside.classList.contains("is-open")) {
      closeAside();
    }
  });

  mobileAsideQuery.addEventListener?.("change", () => {
    syncAsideAccessibility();
  });
}

async function init() {
  bindEvents();
  validateName();
  updateSendAvailability();
  autoResizeTextarea();
  syncAsideAccessibility();
  setAuthenticatedUser(null);

  try {
    await bootstrapAuth();
  } finally {
    await delay(prefersReducedMotion.matches ? 0 : 240);
    hideBootScreen();
  }
}

init();
