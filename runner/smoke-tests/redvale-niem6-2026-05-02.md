# Smoke Test: gpt-5.4-mini vs Sonnet baseline

- Run-dir: `.mapper-runs\redvale\20260413-234605`
- Sample size: 46
- Same target: 38
- Different target: 8
- Failed: 0
- Reasoning effort: `low`
- Seed: 42

## Summary

| Concept | Sonnet | gpt-5.4-mini |
|---|---|---|
| `dbpi:PlanReview` (type) | null | null |
| `dbpi:Payment` (type) | `nc:PaymentType` | `nc:PaymentType` |
| `dbpi:Hearing` (type) | `j:HearingType` | `j:HearingType` |
| `dbpi:CodeSection` (type) | null | null |
| `dbpi:Document` (type) | `nc:DocumentType` | `nc:DocumentType` |
| `dbpi:ViolationCase` (type) | null | `j:OffenseType` |
| `dbpi:PermitTechnician` (type) | `nc:PersonType` | `j:StaffMemberType` |
| `dbpi:PublicService` (type) | `nc:PublicServiceType` | `nc:PublicServiceType` |
| `dbpi:Parcel` (type) | `it:GoodsItemType` | null |
| `dbpi:Person` (type) | `nc:PersonType` | `nc:PersonType` |
| `dbpi:WorkflowState` (type) | null | null |
| `dbpi:PlanReviewer` (type) | `j:StaffMemberType` | `j:StaffMemberType` |
| `dbpi:Organization` (type) | `nc:OrganizationType` | `nc:OrganizationType` |
| `dbpi:Inspector` (type) | `j:StaffMemberType` | `j:StaffMemberType` |
| `dbpi:WorkUnit` (type) | `nc:OrganizationType` | `nc:OrganizationType` |
| `dbpi:ReviewComment` (type) | `nc:CommentType` | `nc:CommentType` |
| `dbpi:Appeal` (type) | `j:AppealType` | `j:AppealType` |
| `dbpi:Address` (type) | `nc:AddressType` | `nc:AddressType` |
| `dbpi:WorkflowTransition` (type) | null | null |
| `dbpi:HearingOfficer` (type) | `j:StaffMemberType` | null |
| `dbpi:NoticeOfViolation` (type) | `nc:DocumentType` | `scr:EnforcementDocumentType` |
| `dbpi:ContactPoint` (type) | `nc:ContactInformationType` | `nc:ContactInformationType` |
| `dbpi:CorrectiveAction` (type) | `j:CorrectiveActionType` | `j:CorrectiveActionType` |
| `dbpi:Division` (type) | `nc:OrganizationType` | `nc:OrganizationType` |
| `dbpi:Inspection` (type) | `j:InspectionType` | `j:InspectionType` |
| `dbpi:InspectionRequest` (type) | null | null |
| `dbpi:Jurisdiction` (type) | `nc:JurisdictionType` | `nc:JurisdictionType` |
| `dbpi:Agent` (type) | `it:AgentType` | `it:AgentType` |
| `dbpi:Department` (type) | `nc:OrganizationType` | `nc:OrganizationType` |
| `dbpi:fromState` (property) | null | null |
| `dbpi:issuedBy` (property) | null | null |
| `dbpi:transitionTrigger` (property) | `em:IncidentResponseActivationTriggerText` | null |
| `dbpi:hasAddress` (property) | null | null |
| `dbpi:requestedWorkType` (property) | `hs:ActionRequestedText` | null |
| `dbpi:hasParcel` (property) | null | null |
| `dbpi:expirationDate` (property) | `nc:ExpirationDate` | `nc:ExpirationDate` |
| `dbpi:dueDate` (property) | `nc:ActivityDueDate` | `hs:DueDate` |
| `dbpi:authorizedPermitType` (property) | `nc:PermitCategoryText` | `nc:PermitCategoryText` |
| `dbpi:longitude` (property) | `cbrn:LongitudeValue` | `cbrn:LongitudeValue` |
| `dbpi:hasInspectionStatus` (property) | null | null |
| `dbpi:hasNotice` (property) | null | null |
| `dbpi:hasCorrectiveAction` (property) | null | null |
| `dbpi:hasInspectionResult` (property) | `cbrn:InspectionResolutionCode` | `cbrn:InspectionResolutionCode` |
| `dbpi:hasWorkflowTransition` (property) | null | null |
| `dbpi:appliesAuthorityId` (property) | null | null |
| `dbpi:hasPlanReview` (property) | null | null |

---

## Detail

## dbpi:PlanReview  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: No candidate is a genuine semantic match for a plan review concept. The three closest candidates each fall short in a distinct way. nc:PlanType represents the plan itself — a proposal for doing something — not the act or record of reviewing one; its properties (PlanApprovalDate, PlanApprovalEntity) are incidental attributes of a plan, not the review activity. em:PlanApprovalType is semantically adjacent — approval implies prior review — but it is scoped specifically to public health event plans and models the approval outcome rather than the review process. em:AfterActionReviewType is structurally the right shape (a review activity extending nc:ActivityType), but its definition explicitly ties it to post-action retrospectives, which is a different review domain. All remaining candidates are biometrics codes, immigration benefit objects, or other unrelated structural types with no semantic overlap. A new extension type (likely from nc:ActivityType) is needed to represent dbpi:PlanReview.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept is a review of a plan, which is not semantically the same as a plan itself or a plan approval/planning container. None of the candidates specifically represent a plan review activity or document. The closest names (nc:PlanType, em:PlanApprovalType, em:PlanningType) are related but do not match the source meaning closely enough, so no genuine semantic match is available.

**Diff**: SAME (targetType)

## dbpi:Payment  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:PaymentType`
- **targetPath**: `nc:PaymentType`
- **rationale**: nc:PaymentType is a direct semantic match for dbpi:Payment. Both represent the concept of a monetary payment. The NIEM type carries exactly the properties you would expect on a payment object — PaymentAmount, PaymentMethodAbstract, and an augmentation point for extensibility — making it a natural reuse target. No other candidate is in the same semantic space; the remaining candidates cover code tables for payment method (nc:PaymentMethodCodeType), financial instruments like bail bonds or invoices, or entirely unrelated domains.

### gpt-5.4-mini
- **targetType**: `nc:PaymentType`
- **targetPath**: `nc:PaymentType`
- **rationale**: The source concept Payment denotes a monetary payment event or entity, which aligns directly with nc:PaymentType. Other candidates are either code values for payment methods or unrelated legal/transaction concepts. nc:PaymentType is the only clear semantic match because it explicitly represents a monetary payment and exposes payment-related properties such as amount and payment method.

**Diff**: SAME (targetType)

## dbpi:Hearing  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:HearingType`
- **targetPath**: `nc:ActivityType/j:HearingType`
- **rationale**: The source concept `dbpi:Hearing` names a formal proceeding — the canonical meaning of "hearing" in legal/administrative contexts. `j:HearingType` is NIEM's general-purpose hearing type with exactly that definition: a proceeding before an administrative agency or authority. Its 54 properties cover the full lifecycle of a hearing (attendees, decisions, witnesses, evidence, cancellation, rescheduling, officials, etc.), making it the comprehensive base type for hearings in NIEM. All other hearing candidates in the list are either specializations of `j:HearingType` (DisciplinaryHearingType, ParoleHearingType, MentalHealthHearingType), sub-components of a hearing (HearingDecisionType, HearingEvidenceType, HearingCancellationType), or unrelated types. With no source definition or superclasses to constrain the match, the generic `j:HearingType` is the correct and direct reuse target.

### gpt-5.4-mini
- **targetType**: `j:HearingType`
- **targetPath**: `nc:ActivityType/j:HearingType`
- **rationale**: The source concept is the general notion of a hearing, not a specialized subtype or related role. Among the candidates, j:HearingType is the direct semantic match because it represents a hearing proceeding itself and serves as the base type for more specific hearing types such as cancellation, decision, request, and specialized hearing variants. Other candidates describe particular kinds of hearings or hearing-related entities, so they are narrower than the source concept.

**Diff**: SAME (targetType)

## dbpi:CodeSection  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept "CodeSection" — given the "dbpi" namespace prefix, which suggests a legal/regulatory document context — likely represents a section of a legal or statutory code (e.g., a numbered provision within a code of law or regulations). None of the candidates are semantically related to this concept. The candidates span biometrics (biom: lip prints, fingerprints, dental, audio capture), emergency management (em: water control, drainage, check-in locations), and education (lrn-dev: sex codes) domains. No candidate represents a legal code section, a document structure element, or any concept that could plausibly align with a statutory or regulatory code section. The match is null.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept is too underspecified to align confidently with any candidate. None of the candidates represent a generic code section or code-list section; they are all domain-specific code/value types (for biometrics, utilities, capture resolution, etc.) with definitions unrelated to 'CodeSection'. Without a source definition or evidence of an existing target property/type for this concept, there is no genuine semantic match.

**Diff**: SAME (targetType)

## dbpi:Document  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:DocumentType`
- **targetPath**: `nc:DocumentType`
- **rationale**: nc:DocumentType is the canonical NIEM representation of a generic document, defined as "a data type for a paper or electronic document." With 65 properties covering authorship, dates, identifiers, format, status, sensitivity, and content, it provides comprehensive coverage of the document concept without domain restriction. The source dbpi:Document carries no definition or superclass constraints, making it a plain document concept that maps directly to nc:DocumentType. All other document-related candidates (it:AdditionalDocumentType, scr:EnforcementDocumentType, j:RapSheetType, etc.) are domain-specific extensions of nc:DocumentType and are therefore too narrow. The remaining candidates (biom:*, scr:DocumentStatus*, lrn-dev:*, etc.) are semantically unrelated. The action is reuse: nc:DocumentType should be used as-is.

### gpt-5.4-mini
- **targetType**: `nc:DocumentType`
- **targetPath**: `nc:DocumentType`
- **rationale**: The source concept is a general Document class with no more specific definition or constraints. nc:DocumentType is the direct semantic match: it represents a paper or electronic document and is the base document type in the target ontology. Other candidates are either specialized kinds of documents, associations involving documents, or augmentations, so they are not as appropriate as the direct reuse candidate.

**Diff**: SAME (targetType)

## dbpi:ViolationCase  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: ViolationCase combines two distinct NIEM concepts: a "case" (nc:CaseType — a legal or administrative matter) and a "violation" (e.g., j:OffenseType — an alleged violation of a statute). No candidate in the list is a genuine semantic match for this combined concept. The closest candidates were evaluated as follows: j:OffenseType captures the violation semantics well (alleged violation of statute/ordinance/rule, with OffenseViolatedStatute and OffenseLevelAbstract properties) but is framed as an activity/incident, not a case — in NIEM, offenses and cases are structurally distinct. hs:ChildSupportEnforcementCaseType has the right structural pattern (extends nc:CaseType, enforcement framing) but is deeply domain-specific to child support and cannot serve as a general ViolationCase base. j:ProhibitedActType captures "violation of a rule/code of conduct" but again is an activity, not a case. No candidate bridges the case-level abstraction with general violation semantics at the appropriate scope. The natural NIEM base for this concept — nc:CaseType — is not present in the candidate list, so the correct action for this source concept is to extend nc:CaseType, not to reuse or augment any of these candidates.

### gpt-5.4-mini
- **targetType**: `j:OffenseType`
- **targetPath**: `nc:ActivityType/j:OffenseType`
- **rationale**: The source term suggests a legal violation-related matter, and among the candidates the closest semantic match is OffenseType because it explicitly represents an alleged violation of a statute, ordinance, or rule. Although the source name includes 'Case', no candidate represents a case of violation more directly, so this is the best available alignment rather than an exact match.

**Diff**: DIFFERENT — Sonnet picked `None`, new model picked `j:OffenseType`

## dbpi:PermitTechnician  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:PersonType`
- **targetPath**: `nc:PersonType`
- **rationale**: PermitTechnician is a subclass of Employee, making it fundamentally a person in a specific occupational role. Among all candidates, nc:PersonType is the correct NIEM base for an extension: a new dbpi:PermitTechnicianType would extend nc:PersonType and carry permit-domain-specific properties. The more specific person-as-employee candidates — j:StaffMemberType (justice agency staff), im:ICEEmployeeType (DHS/ICE employee), im:ICEOfficerType (enforcement officer), j:HearingInvestigatorType (hearing staff) — are all justice or immigration domain types whose inherited properties (badge numbers, weapons assignments, incident links, chain of custody) have no semantic relevance to a permit technician. None of those warrants reuse or extension inheritance. nc:PersonType is the appropriate extension base: it is domain-agnostic, carries general person attributes (name, contact, job title, identification), and is the canonical root from which all NIEM person specializations derive.

### gpt-5.4-mini
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: The source concept is a person-typed employee subclass, and the closest available NIEM concept is a generic staff member/person employed by an agency or institution. It is not an association, credential, permit, or position type, so StaffMemberType is the best semantic fit among the candidates. The match is broad rather than exact because no candidate specifically represents a permit technician role.

**Diff**: DIFFERENT — Sonnet picked `nc:PersonType`, new model picked `j:StaffMemberType`

## dbpi:PublicService  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:PublicServiceType`
- **targetPath**: `nc:PublicServiceType`
- **rationale**: nc:PublicServiceType is an exact semantic match for dbpi:PublicService. Both represent the same domain concept — a service rendered by a public agency to citizens, businesses, or other agencies. The NIEM type is a well-structured object type with properties covering name, description, category, channel, location, language, schedule, input/output resources, and website URI — all properties one would expect on a general-purpose PublicService concept. No other candidate approaches this relevance: j:ServiceCallType is about emergency dispatch calls, cyber:BreachRemediationServiceType is a narrow security remediation concept, and the remaining candidates are code tables or unrelated domain types. The action is reuse — the source concept maps directly to this existing NIEM type as-is.

### gpt-5.4-mini
- **targetType**: `nc:PublicServiceType`
- **targetPath**: `nc:PublicServiceType`
- **rationale**: This is a direct semantic match on the concept of a public service. The candidate nc:PublicServiceType has the same meaning and is an object type specifically intended to represent public services. None of the other candidates are as close; they describe service calls, notifications, code values, or unrelated administrative/legal concepts.

**Diff**: SAME (targetType)

## dbpi:Parcel  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `it:GoodsItemType`
- **targetPath**: `nc:ItemType/it:GoodsItemType`
- **rationale**: The source concept `dbpi:Parcel` carries no definition, so the match rests on domain semantics. "Parcel" in a data/logistics context denotes a discrete package or goods unit being shipped — distinct from a full consignment or shipment and distinct from reusable transport equipment. Among the candidates, `it:GoodsItemType` ("a specific Item sent for sale, storage, or shipment") is the closest semantic fit: it represents an individual goods unit moving through a supply chain, which is the core meaning of a parcel. Its property set (origin/destination location, customs valuation, goods measure, packaging) is structurally appropriate for parcel-level data. The other plausible candidates are either too broad (`it:ConsignmentType` — an entire consignment), too cargo/vessel-centric (`m:CargoType`, `m:CargoItemType`), or focused on reusable transport containers (`it:ShippingContainerType`) rather than the goods unit itself. The recommended action is **extend**: a Parcel is a specialization of a goods item with parcel-specific properties (e.g., parcel ID, dimensions, service class) not already present in `it:GoodsItemType`.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept is too underspecified to establish a reliable alignment. Although several candidates relate to transport or shipment (e.g., CargoType, ShipmentType, ConsignmentType, GoodsItemType), none is a confident semantic match for the generic term "Parcel" without a definition or contextual properties. It could refer to a land parcel, a mail/package parcel, or a shipment-related unit, and the candidate set does not provide a clear equivalent for any of these senses. Therefore no genuine match can be selected.

**Diff**: DIFFERENT — Sonnet picked `it:GoodsItemType`, new model picked `None`

## dbpi:Person  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:PersonType`
- **targetPath**: `nc:PersonType`
- **rationale**: nc:PersonType is the canonical NIEM type for a human being and is the direct semantic match for dbpi:Person. It is the root person type in NIEM (not a subclass of any domain-specific type), carries 84 properties covering identity, demographics, physical characteristics, and contact information, and serves as the base for all domain-specific person subtypes in the candidate list (j:EnforcementOfficialType, im:ICEEmployeeType, j:StaffMemberType, etc.). The source dbpi:Person is a general-purpose person concept — not a law enforcement officer, immigration employee, or other specialized role — so the base nc:PersonType is the correct target. The action is reuse: the source maps directly to this existing NIEM type.

### gpt-5.4-mini
- **targetType**: `nc:PersonType`
- **targetPath**: `nc:PersonType`
- **rationale**: The source concept is Person, a human being, which directly matches nc:PersonType's definition. It is the most general and semantically exact fit among the candidates. More specific person subclasses (e.g., enforcement official, staff member) are not appropriate because the source has no such specialization.

**Diff**: SAME (targetType)

## dbpi:WorkflowState  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: WorkflowState is a generic, domain-agnostic concept for tracking the current phase or status of a workflow process. The candidate set contains several status-related types (j:TitleStatusType, scr:BenefitApplicationStatusType, scr:BenefitDocumentStatusType, j:ConveyanceRegistrationStatusType, em:PercentStatusType, scr:DocumentStatusType), but each is narrowly scoped to a specific domain — vehicle title, immigration benefit, conveyance registration, emergency management, or document handling. None generalizes to "workflow state" as a process-tracking concept. The natural NIEM base would be nc:StatusType, but that is not among the candidates. No candidate is a genuine semantic match for a generic workflow lifecycle state.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept is a very generic workflow state/status concept, but none of the candidates are a genuine semantic match. The available candidates are all domain-specific status or application types (title, benefit document/application, conveyance registration, percent completion, immigration benefit, etc.) or unrelated simple values. There is no generic workflow status type or property to align to, so the safest choice is no match.

**Diff**: SAME (targetType)

## dbpi:PlanReviewer  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: PlanReviewer's sole structural fact is that it subclasses Employee — making it a person in an employment role with a specific functional duty (reviewing plans). Among all candidates, j:StaffMemberType is the closest semantic match: it models a person employed by an organization and extends nc:PersonType with employment-relevant properties (qualifications, identification, status, location). No candidate is specifically a "plan reviewer," so a direct reuse is not possible. The appropriate action is extend — a new extension type would subclass j:StaffMemberType (or nc:PersonType) to carry plan-review-specific properties. Candidates such as j:PanelMemberType (panel membership) and im:ICEEmployeeType (enforcement officer) are too domain-specific. nc:PersonType is too generic to carry the employment semantic inherited from dbpi:Employee. j:StaffMemberType is the best-fit base from which to extend.

### gpt-5.4-mini
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: PlanReviewer is a person role within an employment context, and the source superclass dbpi:Employee indicates the concept is an employee. Among the candidates, j:StaffMemberType is the closest semantic fit because it directly represents an employed person. The more specific hearing/panel/assignment types are role-specific and do not match plan review, and the remaining candidates describe different immigration or personnel concepts.

**Diff**: SAME (targetType)

## dbpi:Organization  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: nc:OrganizationType is the canonical NIEM type for an organization — its definition ("a body of people organized for a particular purpose") maps directly to the source concept. It is a rich object type with 39 properties covering name, identification, location, contact information, status, incorporation, jurisdiction, and sub-units, which represents the full breadth expected of a general-purpose Organization class. No other candidate comes close: the other organization-related candidates are either narrow subtypes (j:VehicleBranderType), partial fragments (biom:OrganizationIdentificationListType, j:OrganizationAlternateNameType), agency-specific specializations (cbrn:AcknowledgingAgencyType, cbrn:RequestAgencyType), code tables (cyber:OrganizationCategoryCodeType), or unrelated types. The source's superclass dbpi:Agent is consistent with NIEM's treatment of organizations as top-level actors alongside persons, which nc:OrganizationType also reflects. The action is reuse: the source concept maps directly to this existing NIEM type with no extension needed.

### gpt-5.4-mini
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: The source concept is Organization, which directly matches the target ontology's core organization entity type. nc:OrganizationType is the canonical object type for an organization and is a much better semantic fit than role-, category-, or relationship-specific candidates. The source is not a code/value type or association, so reuse of nc:OrganizationType is the best alignment.

**Diff**: SAME (targetType)

## dbpi:Inspector  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: dbpi:Inspector is a subclass of dbpi:Employee — a person in a specialized employee role who performs inspections. No candidate directly models an inspector-as-person. j:InspectionType covers the inspection activity, not the inspector. j:EnforcementOfficialType is scoped to law enforcement personnel. j:StaffMemberType is the best structural and semantic foundation: it represents a person employed by an agency or institution (the closest NIEM analog to a general employee), extends nc:PersonType (appropriate for a person role), and carries properties for identification, qualification, and status that an inspector record would plausibly need. The action is extend: dbpi:Inspector is a specialization of employee/staff-member that would require a new type inheriting from j:StaffMemberType to carry inspector-specific properties.

### gpt-5.4-mini
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: The source concept is a kind of Employee, and Inspector is best understood as a staff/person role within an organization rather than an incident, association, or code value. Among the candidates, j:StaffMemberType is the closest semantic match because it directly represents an employed person. The other person-role types are more specialized (e.g., hearing investigator, panel member, enforcement official, ICE officer) and do not generalize as well to Inspector.

**Diff**: SAME (targetType)

## dbpi:WorkUnit  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: dbpi:WorkUnit is a subclass of dbpi:Organization, making it a specialized organizational entity — a unit or subdivision of an organization in a work context. nc:OrganizationType is NIEM's canonical type for any body of people organized for a purpose, and its property set includes OrganizationSubUnit, OrganizationUnitName, and OrganizationBranchName, which align well with the concept of a work unit. The appropriate action is "extend": WorkUnit is a narrower kind of organization and would require a new extension type subclassing nc:OrganizationType. None of the domain-specific subtypes in the candidate list (e.g., j:EnforcementUnitType, hs:CaseWorkerUnitType, em:ServiceCallAssignedUnitType) match the general workplace-unit semantics of WorkUnit — they all carry domain-specific properties that do not apply here.

### gpt-5.4-mini
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: dbpi:WorkUnit is a subtype of Organization and denotes a unit/organizational unit rather than a person, relationship, or simple value. Among the candidates, nc:OrganizationType is the broadest and most semantically compatible match for an organizational body. The more specific candidates are either role/personnel types, associations, or domain-specific units (e.g., enforcement or case worker units) that do not match the generic WorkUnit concept.

**Diff**: SAME (targetType)

## dbpi:ReviewComment  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:CommentType`
- **targetPath**: `nc:CommentType`
- **rationale**: nc:CommentType is the strongest semantic match for dbpi:ReviewComment. It models a structured comment object with author (CommentAuthorText), creation date (CommentCreationDate), content (CommentText), and title (CommentTitleText) — exactly the properties a review comment would carry. The name "ReviewComment" indicates a comment scoped to a review context, which is a specialization of the general comment concept nc:CommentType represents. No other candidate comes close: biom:LongCommentType is a plain character-limited string wrapper with no structured properties; cbrn:RemarksComplexObjectType is a remarks container from a domain-specific (CBRN) context; the review types (j:ParoleHearingDecisionReviewType, j:SubjectAppealDecisionReviewType, em:AfterActionReviewType) model review activities, not comment artifacts attached to reviews. The appropriate action is extend — ReviewComment would subclass nc:CommentType to bind it to a review context.

### gpt-5.4-mini
- **targetType**: `nc:CommentType`
- **targetPath**: `nc:CommentType`
- **rationale**: The source concept represents a review comment, which is semantically a generic comment/remark rather than a specialized review activity or a constrained string value. Among the candidates, nc:CommentType is the closest match because it is the general NIEM comment container for additional information. The other candidates are either specialized domain-specific comment types, simple string/code values, or unrelated review/activity structures.

**Diff**: SAME (targetType)

## dbpi:Appeal  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:AppealType`
- **targetPath**: `nc:ActivityType/j:AppealType`
- **rationale**: j:AppealType is a direct semantic match for dbpi:Appeal. Both represent the same concept: a formal process of seeking review of actions or decisions already made. The NIEM definition ("a process of seeking review of actions or decisions already executed") precisely captures the general meaning of an appeal. j:SubjectAppealType was considered but rejected because it is a specialization scoped to a subject's appeal with additional criminal-justice-specific properties, making it narrower than the unqualified dbpi:Appeal. No other candidate touches the appeal domain. The recommended action is reuse — NIEM already defines this type and no extension or augmentation is needed based on available information.

### gpt-5.4-mini
- **targetType**: `j:AppealType`
- **targetPath**: `nc:ActivityType/j:AppealType`
- **rationale**: The source concept is simply 'Appeal', which semantically matches the legal/process notion of seeking review of an action or decision. Among the candidates, j:AppealType is the direct and broad match: it represents an appeal as an activity and aligns with the source term better than the more specific appellate decision, case, notice, or related subtypes.

**Diff**: SAME (targetType)

## dbpi:Address  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:AddressType`
- **targetPath**: `nc:AddressType`
- **rationale**: nc:AddressType is the canonical NIEM representation of a postal/physical address, carrying the full set of address properties (city, country, state, postal code, delivery point, full text, secondary unit, etc.). With no definition provided for dbpi:Address, the name alone is the signal — a bare "Address" concept in any domain ontology almost universally refers to a geophysical/postal address structure, which is exactly what nc:AddressType models. No other candidate matches: nc:AddressGridType is a grid-coordinate system, nc:ElectronicAddressType is for URLs/IPs, em:ExplicitRecipientAddressType is a messaging-recipient identifier, it:CommunicatorAddressType extends nc:AddressType but adds communication-channel specificity not implied by the source, and nc:LocationType is a broader geospatial container. The reuse action applies — nc:AddressType can be used as-is.

### gpt-5.4-mini
- **targetType**: `nc:AddressType`
- **targetPath**: `nc:AddressType`
- **rationale**: The source concept is simply Address, which semantically matches the NIEM postal/geophysical address type. Among the candidates, nc:AddressType is the direct, general address container with city, country, postal code, state, and related address components. Other candidates are either specialized address subtypes (e.g., electronic address, address grid) or code/simple types for address categories rather than the address entity itself.

**Diff**: SAME (targetType)

## dbpi:WorkflowTransition  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: No candidate matches the semantic concept of a workflow state transition. A WorkflowTransition models directed movement between named states in a state machine — carrying a source state, target state, and trigger/guard semantics. The closest structural candidates are nc:ActivityType (general actions and process steps) and nc:ProgressType (advances toward completion), but neither captures the state-machine semantics of a transition. ActivityType is a container for timestamped activities with duration, status, and scheduling properties — not for modeling directed edges in a workflow graph. The remaining candidates are either domain-specific to immigration, biometrics, or screening, or are code tables and association types, none of which are semantically related to workflow state transitions.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept appears to denote a workflow transition, which is a process-state change or workflow relationship. None of the candidates is a genuine semantic match: the activity/object types describe general activities or domain-specific eligibility/application records, the association type is specifically about custody transfer, and the simple-value candidates are unrelated code types. There is no candidate for workflow transition or a close NIEM-equivalent relationship/object, so no match is appropriate.

**Diff**: SAME (targetType)

## dbpi:HearingOfficer  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:StaffMemberType`
- **targetPath**: `nc:PersonType/j:StaffMemberType`
- **rationale**: No candidate directly models a hearing officer as a person type. NIEM treats the hearing official role as a property reference within j:HearingType (HearingOfficial), not as a standalone typed entity — confirming there is no reuse target. Among candidates, j:StaffMemberType is the best semantic base for extension: it models a person employed by an agency or institution, directly corresponding to dbpi:HearingOfficer's superclass lineage (dbpi:Employee). j:HearingInvestigatorType was considered but is scoped to investigator assignments, not presiding officers. The correct action is extend — a new hearing-officer-specific type should subclass j:StaffMemberType, inheriting the employee-of-agency structure while adding properties specific to the presiding/officiating role.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept denotes a person role: an officer who conducts or presides over a hearing. None of the candidates match that meaning directly. j:StaffMemberType is too broad (any agency employee), j:PanelMemberType is a panel member rather than a hearing officer, and the other hearing-related types describe investigators, witnesses, decisions, evidence, or assignments rather than the officer role itself. Because there is no genuine semantic match among the candidates, the best choice is null.

**Diff**: DIFFERENT — Sonnet picked `j:StaffMemberType`, new model picked `None`

## dbpi:NoticeOfViolation  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:DocumentType`
- **targetPath**: `nc:DocumentType`
- **rationale**: A Notice of Violation is a formal document — its source superclass is dbpi:Document, making nc:DocumentType the structurally correct NIEM base. nc:DocumentType carries 65 properties covering identification, dates, status, subject, submitter, recipient, sensitivity, and other document-level metadata that a Notice of Violation would need. No candidate represents a notice of violation specifically. scr:EnforcementDocumentType (the next closest) is scoped to "document details of an ENFORCEMENT ENCOUNTER" and carries only two properties, making it too narrow and encounter-centric for a general violation notice. The correct action is "extend": a new NoticeOfViolationType should subclass nc:DocumentType and add violation-specific properties.

### gpt-5.4-mini
- **targetType**: `scr:EnforcementDocumentType`
- **targetPath**: `nc:DocumentType/scr:EnforcementDocumentType`
- **rationale**: The source concept is a subclass of dbpi:Document and represents a notice document issued in an enforcement context. Among the candidates, scr:EnforcementDocumentType is the closest semantic and structural match because it also specializes nc:DocumentType and is explicitly about enforcement-related document details. Other candidates are unrelated activities, statuses, eligibility concepts, or overly generic document types, so this is the best alignment.

**Diff**: DIFFERENT — Sonnet picked `nc:DocumentType`, new model picked `scr:EnforcementDocumentType`

## dbpi:ContactPoint  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:ContactInformationType`
- **targetPath**: `nc:ContactInformationType`
- **rationale**: ContactPoint is a standard name for the concept of how to reach a person or organization — exactly what nc:ContactInformationType represents. Its properties (ContactEntity, ContactMeansAbstract, ContactInformationAvailabilityAbstract, ContactInformationCategoryAbstract) cover the full scope of a contact point: who is being contacted, by what means, and when they are reachable. No other candidate comes close: the association types (it:PartyContactAssociationType, nc:LocationContactInformationAssociationType) model relationships rather than the contact point itself; em:ContactRoleType captures a contact's role, not the contact point; and the telephone/radio types are specific contact means, not the general container. nc:ContactInformationType is a direct reuse.

### gpt-5.4-mini
- **targetType**: `nc:ContactInformationType`
- **targetPath**: `nc:ContactInformationType`
- **rationale**: The source concept ContactPoint denotes contact information or a means/location to contact an entity. Among the candidates, nc:ContactInformationType is the closest semantic match because its definition directly covers how to contact a person or organization, and its properties model contact details. Other candidates are less specific or represent related but different ideas, such as a contact role, a party-contact association, or telephone-number-specific types.

**Diff**: SAME (targetType)

## dbpi:CorrectiveAction  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:CorrectiveActionType`
- **targetPath**: `nc:ActivityType/j:CorrectiveActionType`
- **rationale**: j:CorrectiveActionType is an exact nominal and semantic match for dbpi:CorrectiveAction. The NIEM type models a corrective action as an activity (extending nc:ActivityType) with properties covering the plan, resolution, response text, statement, status, and verification — the full lifecycle one would expect from a corrective action concept. Although the source has no definition, the local name is unambiguous, and NIEM already defines a dedicated type for this concept with the appropriate object pattern and relevant properties. No other candidate comes close: the remaining candidates cover disciplinary actions, post-sentence actions, incident codes, or unrelated biometric/immigration types. The recommended action is reuse.

### gpt-5.4-mini
- **targetType**: `j:CorrectiveActionType`
- **targetPath**: `nc:ActivityType/j:CorrectiveActionType`
- **rationale**: The source concept is a corrective action, which semantically aligns with the candidate describing an event or activity that is part of a corrective action plan. This is a direct object-type match and is much closer than the other candidates, which concern disciplinary actions, incidents, immigration declarations, or unrelated code/value types.

**Diff**: SAME (targetType)

## dbpi:Division  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: dbpi:Division is a subclass of dbpi:Organization, meaning it is an organizational entity — specifically a sub-unit within a parent organization. nc:OrganizationType is the canonical NIEM type for any body of people organized for a purpose, and it already includes OrganizationSubUnit and OrganizationSubUnitName properties that directly support the subdivision semantics of Division. No candidate captures "division as a named sub-unit of an organization" more precisely. The appropriate action is "extend": a new extension type (e.g., dbpi:DivisionType) should subclass nc:OrganizationType via rdfs:subClassOf, adding any Division-specific properties not already present in the base type.

### gpt-5.4-mini
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: dbpi:Division is declared as a subclass of dbpi:Organization, so it represents an organizational entity rather than a relationship, code, or value. Among the candidates, nc:OrganizationType is the closest direct semantic match because it is the generic NIEM organization container and can represent a division as a kind of organization. The other candidates are either role/category/value types or more specific organizational specializations that do not match the source concept as well.

**Diff**: SAME (targetType)

## dbpi:Inspection  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `j:InspectionType`
- **targetPath**: `nc:ActivityType/j:InspectionType`
- **rationale**: j:InspectionType is the canonical NIEM type for a general inspection concept — checking or testing against established standards. It is domain-agnostic (not vehicle-specific, not CBRN-specific), extends nc:ActivityType (appropriate for an event/activity), and carries properties for scope and topic that align with a generic Inspection class. The source has no definition or superclasses to narrow the domain, so the broadest, most directly named match is correct. All other inspection-related candidates are either domain-specific subtypes (vehicle, CBRN) or partial constructs (secondary inspection referral/resolution), none of which better represent a plain Inspection concept than j:InspectionType itself.

### gpt-5.4-mini
- **targetType**: `j:InspectionType`
- **targetPath**: `nc:ActivityType/j:InspectionType`
- **rationale**: The source concept is a generic Inspection, which aligns directly with j:InspectionType’s meaning of checking or testing against established standards. Other candidates are more specific variants (vehicle emission, safety, secondary inspection, detection-event-related) or unrelated biometric/metadata types, so j:InspectionType is the best semantic match.

**Diff**: SAME (targetType)

## dbpi:InspectionRequest  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: null
- **targetPath**: `—`
- **rationale**: No candidate adequately captures the combined semantics of an inspection request — a formal request to initiate or schedule an inspection. The two nearest candidates each cover only half the concept: `j:InspectionType` models the inspection activity itself (checking/testing against standards) with no request framing, while `cbrn:RequestDataType` models generic request metadata (agency, datetime, cancel/update flags) with no inspection semantics. `cbrn:SecondaryInspectionReferralType` is thematically adjacent but represents a referral for a secondary inspection, not a request to conduct one. The remaining candidates (vehicle inspections, immigration benefit requests, hearing requests, warrant types, CBRN data types, and code tables) are semantically unrelated to the source concept. Because no candidate unifies the "request" and "inspection" aspects, a new extension type deriving from `nc:ActivityType` (via `j:InspectionType` as a closer base) would be the appropriate path, but that is outside the scope of a direct match.

### gpt-5.4-mini
- **targetType**: null
- **targetPath**: `—`
- **rationale**: The source concept denotes a request for an inspection, not an inspection event or inspection data itself. None of the candidates is a genuine semantic match: j:InspectionType and cbrn:InspectionDataType describe inspections, not requests; the other request types are for different domains (hearing, travel permit, immigration benefit, assignment). Because there is no explicit inspection-request type and no closer existing NIEM type/property to align to, the best choice is no match.

**Diff**: SAME (targetType)

## dbpi:Jurisdiction  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:JurisdictionType`
- **targetPath**: `nc:JurisdictionType`
- **rationale**: nc:JurisdictionType is a direct semantic match for dbpi:Jurisdiction. Both represent the concept of a bounded geopolitical area or authority scope. NIEM defines this as a standalone object type with properties covering identification, location, description, and restriction of authority — all the natural facets of a jurisdiction concept. No other candidate comes close: the association types (j:DocumentJurisdictionAssociationType, j:ActivityJurisdictionAssociationType) model relationships *involving* a jurisdiction rather than the jurisdiction itself, and all remaining candidates represent unrelated concepts (officials, charges, verdicts, etc.). The action is reuse: nc:JurisdictionType already captures exactly what dbpi:Jurisdiction represents, with no extension or augmentation required.

### gpt-5.4-mini
- **targetType**: `nc:JurisdictionType`
- **targetPath**: `nc:JurisdictionType`
- **rationale**: The source concept Jurisdiction directly denotes a geopolitical area or authority boundary, which matches the candidate definition exactly. No more specific property-level mapping is indicated, and this is the clear semantic equivalent among the candidates.

**Diff**: SAME (targetType)

## dbpi:Agent  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `it:AgentType`
- **targetPath**: `it:PartyType/it:AgentType`
- **rationale**: The semantic alignment between dbpi:Agent and it:AgentType is direct and unambiguous. The NIEM type is explicitly defined as "a party authorized to act on behalf of another person, organization or thing," which is the canonical meaning of "Agent" across legal, business, and ontology domains. The type name matches exactly, the definition matches the universal meaning of the source concept, and it carries agent-specific properties (AgentIdentification, AgentAuthorizationIDCategory, AgentStatusText) that would be expected on an agent entity. No other candidate comes close — all other candidates represent unrelated domain concepts (immigration, enforcement, biometrics, radiation, cybersecurity). The action is reuse: this type can be used as-is.

### gpt-5.4-mini
- **targetType**: `it:AgentType`
- **targetPath**: `it:PartyType/it:AgentType`
- **rationale**: The source concept 'Agent' is a broad role-based party concept, and the best available match is the NIEM-style object type for an agent acting on behalf of another party. None of the other candidates are semantically close to a generic agent concept, while it:AgentType is explicitly about an agent/acting-on-behalf relationship and is the closest direct alignment.

**Diff**: SAME (targetType)

## dbpi:Department  (kind=type, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: A department is an organizational unit — a body of people organized for a particular purpose within a larger organization. The superclass relationship dbpi:Department → dbpi:Organization maps directly onto the NIEM type hierarchy anchored at nc:OrganizationType. NIEM's nc:OrganizationType already carries properties directly relevant to departments: OrganizationSubUnit, OrganizationSubUnitName, OrganizationUnitName, OrganizationBranchName, OrganizationParentAbstract. No other candidate comes close semantically — the remaining candidates cover criminal organizations, personnel records, alternate names, identification lists, or unrelated domains. The appropriate action is extend: dbpi:Department requires a new extension type that subclasses nc:OrganizationType, inheriting its organizational properties while allowing department-specific properties to be added.

### gpt-5.4-mini
- **targetType**: `nc:OrganizationType`
- **targetPath**: `nc:OrganizationType`
- **rationale**: The source concept Department is a subtype of Organization, and the closest available target is the generic organization container. None of the other candidates specifically represent a department or organizational subunit more accurately than nc:OrganizationType. Although Department often denotes an organizational division rather than an entire organization, no dedicated department or subunit type is offered, so nc:OrganizationType is the best semantic match.

**Diff**: SAME (targetType)

## dbpi:fromState  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property models a workflow state-machine concept: the origin state of a transition between workflow states. Every candidate in the list belongs to entirely different semantic domains — immigration benefits, driver license status, itinerary departure dates, geographic identification, detention release, and similar government/justice topics. None represents a workflow transition, a workflow state, or the notion of an origin state in a process model. NIEM does not define general-purpose workflow or state-machine types among these candidates, so no match can be made.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents the starting state in a workflow transition (range dbpi:WorkflowState, parent dbpi:WorkflowTransition). None of the candidates describes a workflow transition endpoint or a state-related relationship. The closest candidates are various status/date properties, but they are semantically about immigration, transport, or release statuses and do not match a workflow state value or transition role. Therefore there is no genuine semantic match.

**Diff**: SAME (targetProperty)

## dbpi:issuedBy  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents "the organization that issued this permit" — an object-typed relationship from a permit to an issuing organization. No candidate captures this semantics. The closest surface candidate is j:RegistrationAuthorityName ("a name of an authority, person, or organization which issued a property registration"), but it is a TextType name string on a registration, not an Organization-typed reference on a permit. No NIEM property in the candidate set models an issuing organization reference on a permit type, so no match is appropriate.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents the organization that issued a permit (range dbpi:Organization). None of the candidates model an issuer relationship to an organization. The closest items are permit-related properties such as nc:PermitIdentification or nc:PermitStartDate, but they describe identification or dates, not the issuing authority. Therefore there is no genuine semantic match.

**Diff**: SAME (targetProperty)

## dbpi:transitionTrigger  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `em:IncidentResponseActivationTriggerText`
- **targetPath**: `em:EmergencyIncidentType/em:IncidentResponseActivationTriggerText`
- **rationale**: Despite the domain mismatch (emergency management vs. workflow), em:IncidentResponseActivationTriggerText is semantically the closest candidate: it captures a condition or stimulus that causes a state transition or activation, which is exactly what a `transitionTrigger` on a `WorkflowTransition` type represents. Both carry a string-compatible value describing the precipitating condition. No other candidate approaches this concept — the remaining candidates cover dates, durations, identifications, and domain-specific status fields that bear no semantic relationship to a workflow trigger.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property is a string-valued trigger on a WorkflowTransition, suggesting a general condition or event that causes a transition. None of the candidates match this meaning or the WorkflowTransition context closely enough. The closest lexical candidate, em:IncidentResponseActivationTriggerText, is specific to emergency incident activation rather than workflow transitions, so it is not a genuine semantic match.

**Diff**: DIFFERENT — Sonnet picked `em:IncidentResponseActivationTriggerText`, new model picked `None`

## dbpi:hasAddress  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source represents a generic "has a physical address" relationship from a Property entity to an Address. None of the candidates match this semantics adequately. The address-typed candidates (nc:PersonResidenceAddress, j:SubjectPlannedAlternateAddress, nc:DocumentCoverageAddress) all carry domain-specific meaning — residence of a person, alternate address of a criminal justice subject, or document coverage scope — that doesn't generalize to a property entity having an address. The augmentation candidates (j:AddressAugmentation, scr:AddressAugmentation) contribute supplemental fields to an existing address type rather than linking an entity to an address. Network/electronic address candidates (j:NetworkAddress, nc:ElectronicAddress, cyber:ElectronicAddressAugmentation) refer to IP/URL addresses, not physical ones. The remaining candidates are boolean indicators, comment text, or association types unrelated to the source concept. No candidate represents a generic "entity hasAddress → AddressType" relationship suitable for a real-property or general-purpose domain class.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property is a generic hasAddress relation whose range is dbpi:Address. None of the candidates is a generic address-typed property with equivalent semantics. Several candidates are either specific relationships to particular address kinds (e.g., person residence, planned alternate address) or augmentation properties about an address, which do not match the source relation itself. Therefore there is no genuine semantic match.

**Diff**: SAME (targetProperty)

## dbpi:requestedWorkType  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `hs:ActionRequestedText`
- **targetPath**: `hs:ActionRequestedText`
- **rationale**: The source property captures the type of work being requested on a permit application — semantically, this is the action or work category the applicant is asking to be permitted to perform. Of all the candidates, hs:ActionRequestedText ("An action being requested") is the closest semantic match: both express the concept of what is being requested by an applicant in a formal application context. The remaining candidates are misaligned: nc:PermitCategoryText classifies the permit itself rather than the requested work; nc:PermitUsageText describes what a permit allows (not what is requested); the license and immigration permit candidates are domain-specific and irrelevant. The type mismatch (skos:Concept vs nc:TextType) and the lack of permit-application context in hs:ActionRequestedText mean this match is approximate rather than precise, but it is the best available candidate.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property denotes a requested work type on a permit application and ranges over skos:Concept, suggesting a coded classification rather than a generic text value. None of the candidates is an exact semantic match for a requested work-type concept on a permit application. The closest candidates (e.g., nc:PermitCategoryText, nc:PermitUsageText, nc:LicensePermitClassificationText) describe permit categories, usage, or license classifications, but they are not the same concept and do not align with the source property's application-level context.

**Diff**: DIFFERENT — Sonnet picked `hs:ActionRequestedText`, new model picked `None`

## dbpi:hasParcel  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property `dbpi:hasParcel` expresses a structural relationship between a real-estate property and a land parcel — a concept from the property/cadastral domain. None of the candidates represent this concept. The candidates are drawn from unrelated domains: biometric identifiers, emergency management indicators, immigration eligibility, justice item codes, telephone number flags, customs party relationships, and lien/title data. While some candidates touch on "property" in the legal/justice sense (e.g., `j:ItemCategoryNIBRSPropertyCategoryCode`, `j:LienReleaseReasonText`, `j:TitleLienIndicator`), none of these express a containment or association relationship between a property record and a parcel. No candidate is a genuine semantic match.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property dbpi:hasParcel indicates a relationship to a Parcel entity (range dbpi:Parcel), but none of the candidates represent a parcel, parcel-to-property relationship, or an equivalent property. The available candidates concern multimedia IDs, item categories, indicators, registrations, notifications, and similar unrelated concepts, so there is no genuine semantic match.

**Diff**: SAME (targetProperty)

## dbpi:expirationDate  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `nc:ExpirationDate`
- **targetPath**: `nc:MetadataType, em:AccessType, em:LicenseCertificationRegistrationType, and others`
- **rationale**: The source property is an expiration date on a Permit type. NIEM does not expose a dedicated nc:PermitExpirationDate property in the candidate set. nc:ExpirationDate is the canonical NIEM property for "a date after which information is no longer valid" — exactly the semantics of a permit expiration date. It is used across credential, access, and certification types (em:LicenseCertificationRegistrationType, em:AccessType, em:CredentialClassType), which are domain-adjacent to permits. The other candidates are either scoped to unrelated domains (sentences, bail bonds, disability placements, lien releases) or carry the wrong semantics (nc:PermitRenewalDate is a renewal date, not an expiration date; nc:PermitStartDate is an issuance date). nc:ExpirationDate is the correct general-purpose expiration date property in NIEM and the best available match for this property.

### gpt-5.4-mini
- **targetProperty**: `nc:ExpirationDate`
- **targetPath**: `em:AccessType/nc:ExpirationDate`
- **rationale**: The source is a date indicating when a permit expires. No candidate is an exact permit-expiration property. Among the options, nc:ExpirationDate is the most general semantically aligned match because it denotes a date after which something is no longer valid. More specific candidates such as nc:PermitRenewalDate describe renewal timing rather than expiration, and nc:DocumentExpirationDate is narrower and tied to documents rather than permits.

**Diff**: SAME (targetProperty)

## dbpi:dueDate  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `nc:ActivityDueDate`
- **targetPath**: `nc:ActivityType/nc:ActivityDueDate`
- **rationale**: The source property represents the completion deadline of a corrective action. In NIEM, corrective actions are modeled as activities (j:CorrectiveActionType participates in the activity hierarchy). nc:ActivityDueDate captures exactly this semantics — the date an activity is expected to be completed — and is the domain-agnostic due-date property on the base activity type. nc:TaskDueDate is a plausible alternative, but tasks are a more specific sub-concept than activities, and nc:ActivityDueDate is the more natural home for a corrective-action due date. hs:DueDate is too narrow in domain context (juvenile assessment). nc:ActivityDueDate is the best structural and semantic match.

### gpt-5.4-mini
- **targetProperty**: `hs:DueDate`
- **targetPath**: `hs:JuvenileAggravatingMitigatingAssessmentType/hs:DueDate`
- **rationale**: The source property is a generic due date on a CorrectiveAction, and the best available candidate is the similarly generic due-date property. Although its containing type is specific to a juvenile assessment, its definition matches the source semantics more closely than the more specialized task/report/activity due-date properties. No exact CorrectiveAction-specific dueDate property is present.

**Diff**: DIFFERENT — Sonnet picked `nc:ActivityDueDate`, new model picked `hs:DueDate`

## dbpi:authorizedPermitType  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `nc:PermitCategoryText`
- **targetPath**: `em:AlarmPermitType/nc:PermitCategoryText`
- **rationale**: The source property `authorizedPermitType` sits on `dbpi:Permit` and carries a `skos:Concept` range — it classifies what kind/category of permit is authorized. `nc:PermitCategoryText` is defined as "a kind of permit," directly expressing the category or type of a permit, which aligns with the source concept. All other candidates are either about permit-specific sub-attributes (status, restrictions, endorsements, identification) or scoped to driver licenses or alarm permits in ways that don't generalize to "the type of an authorized permit." The structural difference (skos:Concept vs. nc:TextType) reflects a controlled-vocabulary vs. free-text representation of the same concept, which is acceptable at the semantic alignment level.

### gpt-5.4-mini
- **targetProperty**: `nc:PermitCategoryText`
- **targetPath**: `em:AlarmPermitType/nc:PermitCategoryText`
- **rationale**: The source property is a permit-level attribute whose name indicates the type/category of an authorized permit. Among the candidates, nc:PermitCategoryText is the closest semantic match because it explicitly denotes a kind of permit. Although its range is text rather than skos:Concept and its example path is on AlarmPermitType, it is still more aligned with the source intent than permit-identification, status, restriction, or endorsement properties, which describe different facets of a permit.

**Diff**: SAME (targetProperty)

## dbpi:longitude  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `cbrn:LongitudeValue`
- **targetPath**: `cbrn:GeographicPointType/cbrn:LongitudeValue`
- **rationale**: The source property carries WGS84 longitude as a decimal value. cbrn:LongitudeValue is the only candidate that explicitly represents longitude as decimal degrees (typed cbrn:Angle180Type, range -180 to +180), directly matching the source's xsd:decimal range and WGS84 decimal degree convention. The runner-up, nc:GeographicCoordinateLongitude, uses nc:LongitudeCoordinateType — a structured degrees/minutes/seconds type — which does not align with a simple decimal longitude value. nc:LongitudeDegreeValue carries only the degree component of a DMS coordinate, not a full decimal longitude. cbrn:LongitudeValue is the precise semantic and structural match.

### gpt-5.4-mini
- **targetProperty**: `cbrn:LongitudeValue`
- **targetPath**: `cbrn:GeographicPointType/cbrn:LongitudeValue`
- **rationale**: The source is a decimal longitude value for a geographic centroid, not a relationship or container type. Among the candidates, cbrn:LongitudeValue is the closest semantic match because it directly represents a point's longitude in decimal degrees with the same WGS84-style coordinate meaning. nc:GeographicCoordinateLongitude is also related, but it is described more as a measurement property and is less specific than the explicit longitude value candidate.

**Diff**: SAME (targetProperty)

## dbpi:hasInspectionStatus  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property `dbpi:hasInspectionStatus` carries the status of an inspection (range: skos:Concept, suggesting a controlled vocabulary/code value) on a parent `dbpi:Inspection` type. The only candidate that combines both "inspection" and "status" concepts is `im:NonImmigrantInspectionAdmissionStatus`, but that property is tightly domain-bound to immigration admission processing — it represents the admission status of a non-immigrant entering the country, not a general or building-domain inspection status. Its semantics are not transferable. The other candidates are either boolean pass/fail indicators (not status codes), inspection type containers (not status properties), topic descriptors, resolution text fields, or inspector identifications — none of which represent a status of an inspection in the general sense that `dbpi:hasInspectionStatus` requires. No candidate is a genuine semantic match.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents an inspection status on dbpi:Inspection with range skos:Concept, so it should align to a status-valued property if one exists. None of the candidates is a genuine match: most are boolean indicators, inspection subtypes, or unrelated inspection-related details. im:NonImmigrantInspectionAdmissionStatus is status-like, but it is specifically about non-immigrant inspection/admission and is scoped to immigration benefit eligibility, not a general inspection status on Inspection. Therefore no candidate is a reliable semantic match.

**Diff**: SAME (targetProperty)

## dbpi:hasNotice  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property links a ViolationCase to a structured NoticeOfViolation object — a formal legal/regulatory notice document. No candidate in the list represents this concept. The closest candidate structurally is j:Violation (nc:IncidentType), but it models the violation incident itself, not a notice issued about a violation. The remaining candidates are all text-valued properties capturing descriptive details (categories, reasons, outcomes) and are semantically unrelated to a notice-of-violation association. A Notice of Violation is a distinct formal artifact (a document or record issued to a party), not captured by any candidate here.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property dbpi:hasNotice is an object-style property from ViolationCase to NoticeOfViolation, so the best match would need to represent a notice related to a violation case. None of the candidates describe a notice, notice-of-violation, or a ViolationCase/related association. The closest candidates mention violation or condition violation text, but those are unrelated text properties or generic violation concepts, not the specific notice relationship. Therefore there is no genuine semantic match.

**Diff**: SAME (targetProperty)

## dbpi:hasCorrectiveAction  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property is a typed object relationship: it connects a ViolationCase to a CorrectiveAction as a structured object. No candidate represents this specific relationship. The nearest candidates are j:SanctionDisciplinaryAction ("a correction action assigned as part of a sanction," type nc:DisciplinaryActionType) and j:CaseActivity ("an action and events related to a case," type nc:ActivityType), but both are structurally misaligned: j:SanctionDisciplinaryAction hangs off a SanctionType (not a violation case), and j:CaseActivity is a generic activity container with no corrective-action semantics. The other candidates with "corrective action" in their names (j:CorrectiveActionResolutionText, j:CorrectiveActionVerificationCategoryText, j:CorrectiveActionStatement) are text or document properties nested inside j:CorrectiveActionType — they describe attributes of a corrective action, not a property linking a violation case to one. No candidate is a genuine semantic match for this relationship property.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property denotes an object relation from ViolationCase to a CorrectiveAction. None of the candidates expresses that same relationship or provides a clearly equivalent property. Several candidates mention corrective action, but they are about statements, resolution text, or related action histories rather than the corrective action itself. Therefore there is no genuine semantic match among the candidates.

**Diff**: SAME (targetProperty)

## dbpi:hasInspectionResult  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: `cbrn:InspectionResolutionCode`
- **targetPath**: `cbrn:InspectionResolutionCode`
- **rationale**: The source property hasInspectionResult sits on an Inspection type and has a range of skos:Concept, indicating it carries a coded or controlled-vocabulary value representing the outcome of an inspection. Among all candidates, cbrn:InspectionResolutionCode is the strongest match: it is explicitly defined as a code for the findings resulting from inspection, and its type (cbrncl:InspectionResolutionCodeType) is a code table — directly analogous to a skos:Concept code value. The text variant (cbrn:InspectionResolutionText) is a free-text string rather than a code, so it does not match the skos:Concept range. cbrn:SecondaryInspectionResolution is scoped specifically to secondary inspections, which is narrower than the general inspection result the source models. All boolean indicator candidates represent pass/fail flags rather than a richer result concept. cbrn:InspectionResolutionCode is the closest available NIEM property for a coded inspection outcome.

### gpt-5.4-mini
- **targetProperty**: `cbrn:InspectionResolutionCode`
- **targetPath**: `—`
- **rationale**: The source property is an Inspection-to-result relationship whose range is skos:Concept, so it most likely represents a coded inspection outcome. Among the candidates, cbrn:InspectionResolutionCode is the closest semantic match because it specifically denotes a code for inspection findings. The other inspection-related candidates are either the inspection event itself, a free-text description, or a more general resolution object rather than a concept-valued result property.

**Diff**: SAME (targetProperty)

## dbpi:hasWorkflowTransition  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents a structural link between a workflow model and its state transitions — a process/state-machine concept. None of the candidates address workflow modeling, state transitions, or process flow. The candidate pool covers biometric measurements (biom), travel itinerary dates (it), immigration benefit eligibility (im), driver license withdrawal status (j), person disability indicators (j), vessel movement (m), and cyber backup indicators (cyber). There is no semantic overlap with workflow transition semantics in any candidate. No match is appropriate.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property represents an association from WorkflowModel to WorkflowTransition, but none of the candidates describe workflow modeling or a transition/relationship in that domain. The listed candidates are about itineraries, immigration, biometrics, disability indicators, vessel movement, or other unrelated concepts. No genuine semantic match is present.

**Diff**: SAME (targetProperty)

## dbpi:appliesAuthorityId  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property "appliesAuthorityId" is a string-typed identifier for an authority that governs or applies to a WorkflowModel. No candidate captures this concept. The closest contenders are im:AuthorizationIdentification ("an identification of an authorization") and it:AgentAuthorizationIDCategory ("a code categorizing the identification of a party to act on behalf of another party"), but neither matches: the former identifies a permission/authorization object rather than a governing authority entity, and the latter is a category code rather than an authority identifier. The remaining candidates are either authority name/text properties, jurisdiction codes, domain-specific identifiers (biometrics, immigration, driver licensing), or entity references — none semantically equivalent to a generic identifier for an applying authority in a workflow context.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property appears to be an identifier string for an authority that a workflow applies to. None of the candidates are a genuine semantic match: several are authority-related, but they describe an authority name, text, code, entity, or unrelated identification, not an authority ID on a workflow model. Since there is no clear existing property for this concept among the candidates, the best choice is no match.

**Diff**: SAME (targetProperty)

## dbpi:hasPlanReview  (kind=property, candidateCount=25)

### Sonnet baseline (`evaluatedBy: sonnet`)
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property connects a PermitApplication to a structured PlanReview object — a domain-specific concept from building/land-use permitting. No candidate represents this relationship. The closest candidates (nc:PlanReport, nc:PlanApprovalDate, nc:PlanApprovalEntity) are properties on nc:PlanType, not on a permit application, and they represent reports, approval dates, or approving entities rather than a review process. nc:DocumentApprovedIndicator and nc:ActivityApprovedIndicator are boolean flags, not object links to a review record. None of the candidates capture the semantics of a permit application holding a structured plan review sub-object.

### gpt-5.4-mini
- **targetProperty**: null
- **targetPath**: `—`
- **rationale**: The source property denotes a relationship from a PermitApplication to a PlanReview entity (range dbpi:PlanReview). None of the candidates represent a plan review or a permit application-review relationship. The closest plan-related candidates concern plan approval, plan purpose, or generic plan/report/permit properties, but they do not semantically match a plan review association. Therefore no genuine match is available.

**Diff**: SAME (targetProperty)
