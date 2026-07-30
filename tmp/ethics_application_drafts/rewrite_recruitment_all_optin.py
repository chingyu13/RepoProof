from pathlib import Path
from docx import Document

ROOT = Path("/Users/chingyu/Projects/RepoProof")
OLD = ROOT / "Done" / "RepoProof_COMP5339_Recruitment_OptIn_All_RepoProof_Research_Use_and_Survey_DRAFT.docx"
NEW = ROOT / "Done" / "RepoProof_COMP5339_Recruitment_OptIn_RepoProof_Research_DRAFT.docx"

def replace(doc, old, new):
    for paragraph in doc.paragraphs:
        if paragraph.text == old:
            paragraph.text = new
            return
    raise RuntimeError(f"Paragraph not found: {old}")

doc = Document(OLD)

replace(
    doc,
    "(Optional five-year RepoProof research record and anonymous experience survey)",
    "(Explicit opt-in for all RepoProof research use)",
)
replace(
    doc,
    "We invite you to choose whether your de-identified RepoProof quiz and code-derived research record may be retained for five years and used in individual and aggregate educational research analyses. We also invite you to complete a separate anonymous experience survey.",
    ("We invite you to consent to your de-identified RepoProof quiz and code-derived research record being retained "
     "for five years and used in individual and aggregate educational research analyses. This is the only pathway "
     "for RepoProof research participation: if you do not opt in, your RepoProof record will not be retained or used "
     "for any research analysis."),
)
replace(
    doc,
    "Review the PIS and e-consent at ?. Select YES only if you consent to five-year retention and all research use of your de-identified RepoProof record, including aggregate analysis. If you select NO or do not opt in, your record will not be retained or used for research. This has no effect on the 2% quiz-completion credit or any other mark. The optional anonymous survey is at ?.",
    ("Please review the Participant Information Statement and e-consent at ?. Select YES only if you voluntarily "
     "consent to five-year retention and all research use of your de-identified RepoProof record, including "
     "individual and aggregate analysis. Selecting NO, or not opting in, has no effect on quiz access, feedback, "
     "the 2% completion credit, other marks or academic standing."),
)
replace(
    doc,
    "The normal RepoProof quiz contains five multiple-choice questions and is expected to take about three minutes. The anonymous experience survey takes approximately ? minutes. No interview, focus group or recording is involved.",
    ("The RepoProof quiz contains five multiple-choice questions and is expected to take about three minutes. "
     "Research consent is optional, but completion of the teaching activity is still required for the 2% completion credit."),
)
replace(
    doc,
    "Final opportunity to opt in / complete the anonymous survey: ?.",
    ("Separate optional anonymous survey: After the quiz, you may also choose to complete an anonymous Qualtrics "
     "experience survey at ?. It takes approximately ? minutes. It is separate from the RepoProof research-record "
     "consent above, and a submitted anonymous response cannot later be identified or withdrawn.\n\n"
     "Final opportunity to opt in to RepoProof research use: ?. Final opportunity to submit the anonymous survey: ?."),
)

doc.save(NEW)
print(NEW)
