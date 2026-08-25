const form = document.querySelector("#question-form");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.querySelector("#question").value;
  const filters = { issuing_organization: document.querySelector("#organization").value || null, notice_number: document.querySelector("#notice-number").value || null, document_kind: document.querySelector("#document-kind").value || null };
  const response = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, filters }) });
  const data = await response.json();
  document.querySelector("#result").hidden = false;
  document.querySelector("#answer").textContent = data.answer;
  document.querySelector("#answer-status").textContent = ({grounded:"모델 검증 답변", grounded_demo:"검증된 원문 발췌", insufficient_evidence:"근거 부족"})[data.status] || data.status;
  document.querySelector("#citations").replaceChildren(...data.citations.map((item) => {
    const link = document.createElement("a"); link.href = item.source_url; link.target = "_blank"; link.rel = "noreferrer";
    link.textContent = `${item.document_title} · ${item.section ?? "본문"}${item.page ? ` · p.${item.page}` : ""}`;
    const entry = document.createElement("li"); entry.append(link); return entry;
  }));
});
