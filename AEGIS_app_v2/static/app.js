
const SAN_RAMON = [-33.539, -70.647];
const SAN_RAMON_BOUNDS = L.latLngBounds(
  [-33.575, -70.690],
  [-33.505, -70.605]
);

const map = L.map("map", {
  minZoom: 13,
  maxZoom: 19,
  maxBounds: SAN_RAMON_BOUNDS,
  maxBoundsViscosity: 0.85
}).setView(SAN_RAMON, 14);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let reports = new Map();
let markers = new Map();
let selectedReportId = null;
let selectedReplyId = null;
let lastCommentSignature = "";

const markerIcon = L.divIcon({
  className: "",
  html: '<div class="aegis-marker"></div>',
  iconSize: [34,34],
  iconAnchor: [17,17],
  popupAnchor: [0,-18]
});

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function photoUrl(photo) {
  return photo === "default-avatar.svg"
    ? "/static/default-avatar.svg"
    : `/static/uploads/${encodeURIComponent(photo || "default-avatar.svg")}`;
}

function openReportPanel(latlng) {
  document.getElementById("coordsText").textContent =
    `${latlng.lat.toFixed(5)}, ${latlng.lng.toFixed(5)}`;
  document.getElementById("reportText").value = "";
  document.getElementById("reportPanel").classList.remove("hidden");
  window.pendingLatLng = latlng;
}

map.on("click", e => openReportPanel(e.latlng));

document.querySelectorAll("[data-close]").forEach(btn => {
  btn.addEventListener("click", () => {
    document.getElementById(btn.dataset.close).classList.add("hidden");
  });
});

document.getElementById("saveReport").addEventListener("click", async () => {
  const text = document.getElementById("reportText").value.trim();
  if (!text) return toast("Escribe qué pasó.");

  const r = await fetch("/api/reports", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      lat: window.pendingLatLng.lat,
      lng: window.pendingLatLng.lng,
      text
    })
  });
  const data = await r.json();
  if (!r.ok) return toast(data.error || "No se pudo publicar.");

  document.getElementById("reportPanel").classList.add("hidden");
  addOrUpdateReport(data, true);
  map.setView([data.lat, data.lng], Math.max(map.getZoom(), 15));
  toast("Reporte publicado.");
});

function addOrUpdateReport(r, openPopup=false) {
  reports.set(r.id, r);
  if (!markers.has(r.id)) {
    const marker = L.marker([r.lat, r.lng], {icon: markerIcon}).addTo(map);
    marker.on("click", () => openComments(r.id));
    markers.set(r.id, marker);
  }
  const marker = markers.get(r.id);
  marker.bindPopup(`
    <div class="report-popup">
      <b>${escapeHtml(r.level)} · ${escapeHtml(r.nickname)}</b>
      <p>${escapeHtml(r.text)}</p>
      <small>Toca el pin para ver los comentarios</small>
    </div>
  `);
  if (openPopup) marker.openPopup();
}

async function loadReports() {
  const res = await fetch("/api/reports");
  if (!res.ok) return;
  const data = await res.json();
  data.forEach(r => addOrUpdateReport(r));
}

async function openComments(reportId) {
  selectedReportId = reportId;
  selectedReplyId = null;
  document.getElementById("replyInfo").classList.add("hidden");
  document.getElementById("cancelReply").classList.add("hidden");

  const report = reports.get(reportId);
  document.getElementById("reportTitle").textContent =
    report ? report.text : "Reporte";
  document.getElementById("commentsPanel").classList.remove("hidden");
  await loadComments(true);
}

function setReply(comment) {
  selectedReplyId = comment.id;
  const info = document.getElementById("replyInfo");
  info.textContent = `Respondiendo a ${comment.nickname}`;
  info.classList.remove("hidden");
  document.getElementById("cancelReply").classList.remove("hidden");
  document.getElementById("commentText").focus();
}

document.getElementById("cancelReply").addEventListener("click", () => {
  selectedReplyId = null;
  document.getElementById("replyInfo").classList.add("hidden");
  document.getElementById("cancelReply").classList.add("hidden");
});

function renderComments(comments) {
  const list = document.getElementById("commentsList");
  list.innerHTML = "";

  const byParent = {};
  comments.forEach(c => {
    const key = c.parent_id ?? "root";
    (byParent[key] ||= []).push(c);
  });

  function renderBranch(parentKey, container, depth=0) {
    (byParent[parentKey] || []).forEach(c => {
      const wrapper = document.createElement("div");
      wrapper.className = depth ? "thread" : "";
      const avatar = c.photo
        ? `<img src="${photoUrl(c.photo)}">`
        : escapeHtml(c.nickname.slice(0,1).toUpperCase());

      wrapper.innerHTML = `
        <article class="comment">
          <div class="avatar">${avatar}</div>
          <div class="comment-body">
            <div class="comment-head">
              <b>${escapeHtml(c.nickname)}</b>
              <span class="level">${escapeHtml(c.level)}</span>
            </div>
            <div class="comment-text">${escapeHtml(c.text)}</div>
            <div class="comment-actions">
              <button data-like="${c.id}">♥ ${c.likes}</button>
              <button data-reply="${c.id}">Responder</button>
            </div>
          </div>
        </article>
      `;
      container.appendChild(wrapper);
      renderBranch(c.id, wrapper, depth+1);
    });
  }

  renderBranch("root", list);

  list.querySelectorAll("[data-like]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.like;
      const res = await fetch(`/api/comments/${id}/like`, {method:"POST"});
      if (res.ok) loadComments(true);
    });
  });

  list.querySelectorAll("[data-reply]").forEach(btn => {
    btn.addEventListener("click", () => {
      const c = comments.find(x => x.id == btn.dataset.reply);
      if (c) setReply(c);
    });
  });
}

async function loadComments(force=false) {
  if (!selectedReportId) return;
  const res = await fetch(`/api/reports/${selectedReportId}/comments`);
  if (!res.ok) return;
  const comments = await res.json();
  const sig = comments.map(c => `${c.id}:${c.likes}:${c.text}`).join("|");
  if (force || sig !== lastCommentSignature) {
    lastCommentSignature = sig;
    renderComments(comments);
  }
}

document.getElementById("sendComment").addEventListener("click", async () => {
  const text = document.getElementById("commentText").value.trim();
  if (!selectedReportId || !text) return;

  const res = await fetch(`/api/reports/${selectedReportId}/comments`, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({text, parent_id:selectedReplyId})
  });
  const data = await res.json();
  if (!res.ok) return toast(data.error || "No se pudo comentar.");

  document.getElementById("commentText").value = "";
  selectedReplyId = null;
  document.getElementById("replyInfo").classList.add("hidden");
  document.getElementById("cancelReply").classList.add("hidden");
  lastCommentSignature = "";
  await loadComments(true);
});

// -------- Perfil --------
const profileDrawer = document.getElementById("profileDrawer");
const profileOverlay = document.getElementById("profileOverlay");
const displayLevel = document.getElementById("displayLevel");
const rangeFill = document.getElementById("rangeFill");
const rangeStatus = document.getElementById("rangeStatus");

const levels = ["Novata", "Vigía", "Guardiana", "AEGIS"];
const levelPercent = {Novata: 0, Vigía: 33, Guardiana: 66, AEGIS: 100};

function openProfile() {
  profileDrawer.classList.remove("hidden");
  profileOverlay.classList.remove("hidden");
  loadProfile();
}

function closeProfile() {
  profileDrawer.classList.add("hidden");
  profileOverlay.classList.add("hidden");
}

document.getElementById("profileBtn").addEventListener("click", openProfile);
document.getElementById("closeProfile").addEventListener("click", closeProfile);
profileOverlay.addEventListener("click", closeProfile);

function setupLevelOptions(actualLevel, displayedLevel) {
  const actualIndex = levels.indexOf(actualLevel);
  displayLevel.innerHTML = "";
  levels.forEach((level, i) => {
    const option = document.createElement("option");
    option.value = level;
    option.textContent = level + (i > actualIndex ? " · bloqueado" : "");
    option.disabled = i > actualIndex;
    option.selected = level === displayedLevel;
    displayLevel.appendChild(option);
  });
  updateRangeUI(displayedLevel || actualLevel);
}

function updateRangeUI(level) {
  const safe = levels.includes(level) ? level : "Novata";
  rangeStatus.textContent = safe;
  rangeFill.style.width = levelPercent[safe] + "%";
}

displayLevel.addEventListener("change", () => updateRangeUI(displayLevel.value));

async function loadProfile() {
  const res = await fetch("/api/me");
  if (!res.ok) return;
  const data = await res.json();

  document.getElementById("drawerNickname").textContent = data.nickname;
  document.getElementById("editNickname").value = data.nickname;
  document.getElementById("editRealName").value = data.real_name || "";
  document.getElementById("drawerLevel").textContent = data.displayed_level || data.level;
  document.getElementById("drawerAvatar").src = photoUrl(data.photo);
  setupLevelOptions(data.level, data.displayed_level || data.level);
}

document.getElementById("saveProfile").addEventListener("click", async () => {
  const payload = {
    nickname: document.getElementById("editNickname").value.trim(),
    real_name: document.getElementById("editRealName").value.trim(),
    displayed_level: displayLevel.value
  };

  const res = await fetch("/api/profile", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) return toast(data.error || "No se pudo guardar.");

  document.getElementById("drawerNickname").textContent = data.nickname;
  document.getElementById("drawerLevel").textContent = data.displayed_level;
  toast("Perfil actualizado.");
  setTimeout(() => window.location.reload(), 450);
});

document.getElementById("drawerPhoto").addEventListener("change", async e => {
  const file = e.target.files[0];
  if (!file) return;

  const preview = URL.createObjectURL(file);
  document.getElementById("drawerAvatar").src = preview;

  const form = new FormData();
  form.append("photo", file);
  const res = await fetch("/api/profile/photo", {method:"POST", body:form});
  const data = await res.json();
  if (!res.ok) return toast(data.error || "No se pudo cambiar la foto.");

  toast("Foto actualizada.");
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/logout", {method:"POST"});
  window.location.href = "/profile";
});

// -------- Navegación superior --------
document.getElementById("mapNav").addEventListener("click", () => {
  map.setView(SAN_RAMON, 14);
});

document.getElementById("myLevelNav").addEventListener("click", openProfile);

const infoModal = document.getElementById("infoModal");
document.getElementById("howNav").addEventListener("click", () => {
  infoModal.classList.remove("hidden");
});
document.getElementById("closeInfo").addEventListener("click", () => {
  infoModal.classList.add("hidden");
});

loadReports();
setInterval(loadReports, 1000);
setInterval(() => loadComments(false), 1000);
