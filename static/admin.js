// admin.js — liga botões de ação à API JSON
async function postForm(url, data) {
  const form = new FormData();
  Object.entries(data).forEach(([k,v]) => form.append(k, v));
  const res = await fetch(url, { method: "POST", body: form });
  return res.json();
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;

  const action = btn.dataset.action;
  const tr = btn.closest("tr");
  if (!action || !tr) return;

  const user = tr.dataset.user;

  if (action === "toggle") {
    const out = await postForm("/admin/toggle", { user });
    if (out.ok) location.reload();
    else alert(out.msg || "Falha ao alternar status.");
  }

  if (action === "delete") {
    if (!confirm(`Excluir usuário "${user}"?`)) return;
    const out = await postForm("/admin/delete", { user });
    if (out.ok) location.reload();
    else alert(out.msg || "Falha ao excluir.");
  }
});

const createForm = document.getElementById("createForm");
if (createForm) {
  createForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(createForm);
    const out = await fetch("/admin/create", { method: "POST", body: fd }).then(r => r.json());
    if (out.ok) {
      document.querySelector("#createModal .btn-close").click();
      location.reload();
    } else {
      alert(out.msg || "Falha ao criar usuário.");
    }
  });
}
