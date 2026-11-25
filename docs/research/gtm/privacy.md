# Privacy rules for street-level capture for a BC municipality

Question: what privacy rules apply when a contractor captures street-level imagery and LiDAR for a BC municipality, and what anonymisation is required? (GitHub issue #478; parent map #485.) Research note, read 2026-11-24; not legal advice.

## Short answer

- The city is a public body, so FOIPPA governs its records. The contractor is a service provider: Part 3 binds the contractor's employees and associates as if city staff, and the city cannot contract out (FOIPPA s.3(2)(b); [S1](#s1); [S11](#s11), accessed 2026-11-24).
- Collection needs a listed authority, in practice s.26(c); notice (s.27); security (s.30); use (s.32); disclosure (s.33), outside Canada (s.33.1); retention of at least one year only where a decision directly affects the individual (s.31) ([S2](#s2), accessed 2026-11-24).
- The contractor as an organisation is also subject to PIPA, but PIPA does not apply to personal information to which FOIPPA applies; the split runs by information and purpose, not by record (PIPA s.1 "organization" excludes a public body; PIPA s.3(2)(d); [S4](#s4), accessed 2026-11-24).
- A non-ministry public body must conduct a PIA (FOIPPA s.69(5.3)), in accordance with the minister's directions; the commissioner's review is comment, not approval ([S3](#s3); [S7](#s7), accessed 2026-11-24).
- Faces and licence plates are personal information only when linked to an identifiable individual; identifiability depends on context ([S1](#s1), accessed 2026-11-24).
- No blanket prohibition on storing personal information outside Canada since 2021: former s.30.1 was repealed by Bill 22 (2021); s.33.1 plus B.C. Reg. 294/2021 govern disclosure outside Canada, with a supplementary assessment for sensitive information ([S5](#s5); [S6](#s6); [S7](#s7), accessed 2026-11-24).

## FOIPPA and PIPA duties

The city is a public body, so FOIPPA governs records in its custody or control. Part 3 binds the contractor's employees and associates (FOIPPA s.3(2)(b)); the city cannot contract out of Part 3 ([S1](#s1); [S11](#s11), accessed 2026-11-24). The contractor as an organisation is also subject to PIPA, but PIPA does not apply to personal information to which FOIPPA applies (PIPA s.3(2)(d)); the split runs by information and purpose, not by record (PIPA s.1 "organization" excludes a public body; [S4](#s4), accessed 2026-11-24). The contractor remains responsible for personal information under its control even when not in its custody (PIPA s.4(2); [S4](#s4), accessed 2026-11-24).

Under FOIPPA, collection is only under a listed authority, e.g. s.26(c), necessary for a program or activity (FOIPPA s.26; [S2](#s2), accessed 2026-11-24). Notice: purpose, legal authority, contact information, subject to exceptions (FOIPPA s.27; [S2](#s2), accessed 2026-11-24). Security: reasonable arrangements against unauthorised collection, use, disclosure or disposal (FOIPPA s.30; [S2](#s2), accessed 2026-11-24). Use limited to the collection purpose or a consistent purpose (FOIPPA s.32; [S2](#s2), accessed 2026-11-24). Disclosure only in listed circumstances (FOIPPA s.33; [S2](#s2), accessed 2026-11-24); disclosure outside Canada only in accordance with the regulations (FOIPPA s.33.1; [S2](#s2), accessed 2026-11-24). Retention of at least one year only where PI is used to make a decision directly affecting the individual (FOIPPA s.31; [S2](#s2), accessed 2026-11-24). A non-ministry public body must conduct a PIA in accordance with the minister's directions (FOIPPA s.69(5.3)); a PIA assesses whether a current or proposed enactment, system, project, program or activity meets Part 3 (FOIPPA s.69(1); [S3](#s3), accessed 2026-11-24).

Under PIPA, an organisation must not collect, use or disclose personal information without consent unless authorised (PIPA s.6; [S4](#s4), accessed 2026-11-24). Collection for appropriate purposes (PIPA s.11; [S4](#s4), accessed 2026-11-24). Purposes disclosed on or before collection (PIPA s.10; [S4](#s4), accessed 2026-11-24). Use limited to disclosed purposes (PIPA s.14; [S4](#s4), accessed 2026-11-24), with exceptions (PIPA s.15; [S4](#s4), accessed 2026-11-24). Collection without consent by observation at a public event (PIPA s.12(1)(d); [S4](#s4), accessed 2026-11-24). Reasonable security arrangements required (PIPA s.34; [S4](#s4), accessed 2026-11-24). Retention of at least one year where PI is used to make a decision directly affecting the individual (PIPA s.35(1); [S4](#s4), accessed 2026-11-24); destruction or removal of the means of association required when the purpose is no longer served (PIPA s.35(2); [S4](#s4), accessed 2026-11-24).

Personal information under both statutes means information about an identifiable individual. An image of a licence plate is personal information when linked to an identifiable individual — in practice, because plates can be matched to registered owners through motor-vehicle records. Whether a particular image is personal information depends on context ([S1](#s1); [S10](#s10), accessed 2026-11-24).

LiDAR raises the same statutory test: whether the record is recorded information about an identifiable individual, not which sensor captured it (FOIPPA s.1 and Schedule 1; [S1](#s1), accessed 2026-11-24). Colourised or fused point clouds can contain personal information, and raw geometric LiDAR may still permit identification in context. Anonymisation means de-identification or blurring where applicable plus a re-identification-risk assessment; blurring is not a guarantee. No LiDAR-specific OIPC guidance was found; see What is not established.

## OIPC guidance and decisions

OIPC public-sector surveillance guidelines (undated): apply FOIPPA to video and audio surveillance by public bodies, including body-worn cameras, dash cams, drones and fixed cameras; require s.26 authority; require a PIA before implementing; consent is not a viable authority; data minimisation; annual PIA review ([S15](#s15), accessed 2026-11-24).

OIPC dash-cam blog, "Dash-cam video and the challenges of consent" (Bradley Weldon, Acting Deputy Commissioner, 2017-08-17): private-sector dash-cam use is likely unlawful under PIPA because consent cannot be obtained from people on public streets ([S8](#s8), accessed 2026-11-24).

Richmond public safety camera field test: Investigation Report 26-01 / Order F26-01, January 2026 ([S9](#s9), accessed 2026-11-24).

ALPR by Victoria Police: Investigation Report F12-04, 2012-11-15 ([S10](#s10), accessed 2026-11-24).

OIPC data services contracts guidance (May 2003): contracting out does not relieve Part 3 obligations; contracts should require service provider compliance with FIPPA ([S11](#s11), accessed 2026-11-24).

OIPC body-worn camera guidance: records are personal information about identifiable individuals; PIA recommended as a best practice; a clear policy framework is called for ([S12](#s12), accessed 2026-11-24).

Joint letter to Google re StreetView (2009-08-21): Google proposed retaining unblurred images for a maximum of one year after publication, then permanent blur; unblurred images need appropriate security; knowledge and consent required. References "Captured on Camera — Street-level imaging technology, the Internet and you" ([S14](#s14), accessed 2026-11-24).

OIPC guidance, "Section 30: reasonable security measures for disclosures outside of Canada" (2022): outside-Canada disclosure requires a very high level of rigour; unlikely to meet s.30 without rule of law or adequate privacy laws ([S13](#s13), accessed 2026-11-24).

## Usual practice

In practice, blurring is applied to published imagery, with a request/takedown route; vendor practice, not law ([S14](#s14), accessed 2026-11-24).

If — and only if — the imagery is used to make a decision that directly affects an identifiable individual, FOIPPA s.31 and PIPA s.35(1) require retention for at least one year after use. For the contractor as an organisation, PIPA s.35(2) requires destruction or removal of the means of association when the purpose is no longer served. For the city, FOIPPA s.32 limits use; FOIPPA imposes no general destruction duty, and disposal follows the public body's records retention and disposition schedule ([S16](#s16), accessed 2026-11-24). PIPA s.35(2) means destruction or removal of the means of association ([S2](#s2); [S4](#s4), accessed 2026-11-24).

FOIPPA s.69(5.3) requires the head of a public body that is not a ministry to conduct a privacy impact assessment in accordance with the minister's directions; s.69(1) defines a PIA as an assessment against Part 3 for a system, project, program or activity. OIPC surveillance guidance calls for a PIA before implementing a surveillance system and an annual review ([S15](#s15)); the commissioner's review and comment is not approval (inference from s.69(5.1)/(5.4); [S3](#s3), accessed 2026-11-24).

Since 2021 there is no blanket prohibition on storing or accessing personal information outside Canada. Former s.30.1 was repealed by Bill 22 (2021). The current rule is that a public body may disclose personal information outside Canada only in accordance with the regulations (FOIPPA s.33.1; B.C. Reg. 294/2021), and where sensitive personal information is disclosed to be stored outside Canada a supplementary assessment is required. Geolocation data is commonly treated as sensitive. Security duties (s.30) continue to apply, and OIPC guidance calls for a very high level of rigour for outside-Canada disclosure ([S5](#s5); [S6](#s6); [S13](#s13); [S7](#s7), accessed 2026-11-24).

Checks to consider:

- Identify and document s.26 authority before capture, and complete a PIA per s.69(5.3) with the outside-Canada assessment where sensitive information is stored abroad.
- Contract for service-provider status, storage location, and destruction on termination.
- Blur faces and plates before publication with a takedown route, labelled practice; set retention: one-year minimum only where a decision directly affects an individual, otherwise destroy or de-identify when the purpose is served.

## What is not established

- Richmond: Investigation Report 26-01 / Order F26-01, January 2026; exact day not printed on the PDF ([S9](#s9), accessed 2026-11-24).
- "Captured on Camera — Street-level imaging technology, the Internet and you" was not retrieved; referenced in the 2009 joint letter only ([S14](#s14), accessed 2026-11-24).
- No LiDAR-specific OIPC guidance was found; the analysis above applies the general statutory test and de-identification practice.
- Whether the contractor's own processing (for example training models on captured imagery) falls under FOIPPA or PIPA is not resolved and needs counsel.
- Storage-versus-disclosure scope: s.33.1 regulates disclosure outside Canada; storage is assessed as part of that disclosure and the supplementary assessment; any successor provision specifically covering storage is not confirmed here.
- Currency of dated OIPC guidance: surveillance guidelines undated on source; data services contracts guidance May 2003; outside-Canada security guidance 2022. BC government guidance last updated 2025-02-13.
- De-identification limits: de-identified data may still be personal information in some contexts; blurring is not a guarantee.
- No prices are in scope.

This note is research, not legal advice. Consult counsel before contracting or publishing imagery.

## Sources

1. <a id="s1"></a> **S1 · Law (primary)** — King's Printer. FOIPPA (complete Act, incl. Schedule 1). https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/96165_00. Accessed 2026-11-24. Supports: s.1, s.3(2)(b), Schedule 1.

2. <a id="s2"></a> **S2 · Law (primary)** — King's Printer. FOIPPA Part 3 (ss.26–33.1). https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/96165_03. Accessed 2026-11-24. Supports: s.26-s.33.1.

3. <a id="s3"></a> **S3 · Law (primary)** — King's Printer. FOIPPA s.69. https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/96165_06. Accessed 2026-11-24. Supports: s.69(5.3); s.69(1).

4. <a id="s4"></a> **S4 · Law (primary)** — King's Printer. PIPA [SBC 2003] c.63. https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/03063_01. Accessed 2026-11-24. Supports: PIPA s.1, s.3(2)(d), s.4(2), s.6, s.10-s.15, s.34, s.35.

5. <a id="s5"></a> **S5 · Law (primary)** — King's Printer. Bill 22 (2021), s.17 (repeal of s.30.1). https://www.bclaws.gov.bc.ca/civix/document/id/hstats/hstats/1202395030. Accessed 2026-11-24. Supports: repeal of s.30.1.

6. <a id="s6"></a> **S6 · Law (primary)** — Province of BC. B.C. Reg. 294/2021. https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/294_2021. Accessed 2026-11-24. Supports: regulation under s.33.1.

7. <a id="s7"></a> **S7 · BC gov (primary)** — Province of BC. Guidance on Disclosures Outside of Canada. https://www2.gov.bc.ca/gov/content/governments/services-for-government/information-management-technology/privacy/privacy-impact-assessments/guidance-on-disclosures-outside-of-canada. Accessed 2026-11-24. Supports: supplementary assessment; geolocation sensitive.

8. <a id="s8"></a> **S8 · OIPC (primary)** — OIPC BC. Dash-cam video and the challenges of consent (Bradley Weldon). 2017-08-17. https://oipc.bc.ca/blog/news/dash-cam-video-and-the-challenges-of-consent/. Accessed 2026-11-24. Supports: dash-cam use likely unlawful.

9. <a id="s9"></a> **S9 · OIPC (primary)** — OIPC BC. Richmond Public Safety Camera Field Test. January 2026. https://www.oipc.bc.ca/documents/investigation-reports/3073. Accessed 2026-11-24. Supports: Richmond field test.

10. <a id="s10"></a> **S10 · OIPC (primary)** — OIPC BC. ALPR by Victoria Police, F12-04. 2012-11-15. https://www.oipc.bc.ca/documents/investigation-reports/1410. Accessed 2026-11-24. Supports: ALPR investigation.

11. <a id="s11"></a> **S11 · OIPC (primary)** — OIPC BC. Data Services Contracts guidance. May 2003. https://www.oipc.bc.ca/documents/guidance-documents/1393. Accessed 2026-11-24. Supports: contracting out obligations.

12. <a id="s12"></a> **S12 · OIPC (primary)** — OIPC BC. Body-Worn Cameras by Law Enforcement. https://www.oipc.bc.ca/documents/guidance-documents/1668. Accessed 2026-11-24. Supports: body-worn camera PI and PIA.

13. <a id="s13"></a> **S13 · OIPC (primary)** — OIPC BC. Section 30: reasonable security outside Canada. 2022. https://www.oipc.bc.ca/documents/guidance-documents/2486. Accessed 2026-11-24. Supports: rigour for outside-Canada disclosure.

14. <a id="s14"></a> **S14 · OIPC (primary)** — OIPC BC et al. Re: Google StreetView joint letter. 2009-08-21. https://oipc.bc.ca/media/6166/joint-letter-google-streetview.pdf. Accessed 2026-11-24. Supports: one-year retention; security; consent.

15. <a id="s15"></a> **S15 · OIPC (primary)** — OIPC BC. Public sector surveillance guidelines. Undated; PDF created 2026-01-14. https://www.oipc.bc.ca/documents/guidance-documents/3072. Accessed 2026-11-24. Supports: s.26; PIA.

16. <a id="s16"></a> **S16 · BC gov (primary)** — Province of BC. Information schedules. Last updated 2026-03-31. https://www2.gov.bc.ca/gov/content/data/information-management/information-schedules. Accessed 2026-11-24. Supports: records retention schedule.
