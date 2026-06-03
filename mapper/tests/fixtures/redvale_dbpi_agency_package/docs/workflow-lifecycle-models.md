# City of Red Vale DBPI Workflow Lifecycle Models

This document defines the canonical lifecycle models used by the Department for core operational records.

## 1. Permit Application Lifecycle

### States
- **Received** — submission accepted into the system
- **Under Review** — routed for technical and administrative review
- **Approved** — review complete and eligible for issuance
- **Denied** — application rejected on substantive grounds
- **Withdrawn** — applicant withdraws before issuance

### Allowed transitions
- Received → Under Review
- Under Review → Approved
- Under Review → Denied
- Under Review → Withdrawn
- Received → Withdrawn

### Typical transition triggers
- completeness verified
- routing complete
- all review disciplines approved
- fatal noncompliance identified
- applicant request to withdraw

## 2. Permit Lifecycle

### States
- **Active** — permit issued and valid
- **Suspended** — work temporarily halted or permit status paused
- **Revoked** — authorization terminated before completion
- **Expired** — permit lapsed by time or inactivity
- **Finaled** — work completed and final approval granted

### Allowed transitions
- Active → Suspended
- Active → Revoked
- Active → Expired
- Active → Finaled
- Suspended → Active
- Suspended → Revoked
- Suspended → Expired

### Typical transition triggers
- stop-work or compliance hold
- reinstatement after correction
- time expiration
- final inspection approval
- serious fraud or unlawful continuation

## 3. Inspection Request / Inspection Lifecycle

### Request states
- **Requested** — request received
- **Scheduled** — appointment assigned
- **Canceled** — request canceled before performance
- **Completed** — request fulfilled by inspection

### Inspection result states
- **Pass**
- **Partial Pass**
- **Fail**
- **No Access**

### Typical request transitions
- Requested → Scheduled
- Requested → Canceled
- Scheduled → Completed
- Scheduled → Canceled

### Typical result triggers
- work conforms
- some items conform and some do not
- cited deficiencies found
- site inaccessible or not ready

## 4. Violation Case Lifecycle

### States
- **Open** — case created and under investigation
- **Pending Compliance** — violation confirmed and awaiting correction
- **Referred** — escalated to hearing, legal, or another authority
- **Closed** — matter resolved or dismissed

### Allowed transitions
- Open → Pending Compliance
- Open → Closed
- Pending Compliance → Closed
- Pending Compliance → Referred
- Referred → Closed

### Typical transition triggers
- evidence confirms violation
- no violation or outside jurisdiction
- corrective action completed
- noncompliance persists beyond deadline
- legal or hearing outcome entered

## 5. Appeal Lifecycle

### States
- **Pending** — appeal accepted and awaiting disposition
- **Granted** — decision modified in favor of appellant
- **Denied** — original action sustained

### Allowed transitions
- Pending → Granted
- Pending → Denied

### Typical transition triggers
- hearing officer determination
- withdrawal on the record with final disposition entry

## 6. Records Request Lifecycle

### States
- **Received**
- **In Review**
- **Fulfilled**
- **Partially Fulfilled**
- **Denied**
- **Closed**

### Allowed transitions
- Received → In Review
- In Review → Fulfilled
- In Review → Partially Fulfilled
- In Review → Denied
- Fulfilled → Closed
- Partially Fulfilled → Closed
- Denied → Closed

### Typical transition triggers
- request sufficiently specific
- records located and released
- records released with lawful redactions or partial withholding
- exemption or inability to locate responsive records
- administrative completion

## Cross-cutting rules

1. Every lifecycle state change must be attributable to an actor, date/time, and authority or business reason.
2. Adverse transitions should be associated with notice text or recorded justification.
3. A workflow state does not itself replace the underlying legal authority; it operationalizes it.
4. Downstream systems should treat these models as authoritative for process-state semantics.
