# CARE ethics drafting template contract

- Source templates remain unchanged in `docs/ethics/`.
- Outputs are working-copy derivatives saved only in `Done/`.
- Template set: CARE prospective PIS, e-consent, recruitment opt-in, recruitment opt-out (v1b, 15 August 2025).
- Umbrella source: Microsoft Forms printout PDF (v1a). Because it is not a fillable form, the output is a structured response draft that follows the form question order for copy/paste.
- Preserve: page size, margins, header/footer, heading hierarchy, fonts, University/CARE boilerplate, HREC contact details.
- Replace: all bracketed instructions and irrelevant examples.
- Delete as inapplicable: interviews, focus groups, recordings, transcript review, interpreters, and direct access to academic records.
- Unknown facts are represented as `?`.
- Study title: `RepoProof: Evaluating a personalised code-understanding quiz in COMP5339`.
- Consent architecture:
  - cohort aggregate analytics from routine quiz data: CARE-approved opt-out proposed;
  - linked individual five-year de-identified research record: explicit opt-in;
  - anonymous experience survey: optional opt-in and withdrawable until submission.
- Operational data deletion: one month after quiz deadline.
- Research data retention: five years in University Research Data Store, then disposal under University procedures.
- Production hosting: AWS EC2, Sydney region, encrypted EBS; no routine application backups.
- Identity separation: independent CARE staff controls SID–RepoID–FolderID linkage; RepoProof receives no SID.
- Disclosure control: report only groups with n >= 5 and avoid complementary-cell disclosure.

