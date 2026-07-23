"""
build_seed_data.py
------------------
Single source of truth for the compliance control libraries.

Running this script (re)generates the JSON files consumed by:
  * the Django seeder            (compliance/management/commands/seed_frameworks.py)
  * the folder-tree generator    (compliance/management/commands/generate_folder_tree.py)

Control IDs and short titles are functional identifiers. The "objective"
fields are brief, original-wording paraphrases of each control's intent --
they are NOT the normative text of the standards. ISO/IEC 27001 and PCI DSS
are copyrighted; paste the official control text into the app only if your
organisation holds a licence for the source documents.

Usage:
    python tools/build_seed_data.py
"""
import json
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "compliance", "data")
os.makedirs(OUT_DIR, exist_ok=True)


def c(cid, title, objective):
    """Shorthand for a control record."""
    return {"control_id": cid, "title": title, "objective": objective}


# ---------------------------------------------------------------------------
# SOC 2 -- Trust Services Criteria (2017, incl. 2022 points-of-focus revision)
# ---------------------------------------------------------------------------
SOC2 = {
    "key": "soc2",
    "name": "SOC 2",
    "version": "2017 TSC (rev. 2022)",
    "authority": "AICPA",
    "description": "Trust Services Criteria for Security, Availability, "
                   "Processing Integrity, Confidentiality and Privacy.",
    "categories": [
        {
            "key": "CC1", "name": "CC1 - Control Environment",
            "controls": [
                c("CC1.1", "Integrity and ethical values", "The entity demonstrates a commitment to integrity and ethical values."),
                c("CC1.2", "Board oversight", "The board exercises independent oversight of internal control."),
                c("CC1.3", "Organisational structure", "Management establishes structures, reporting lines, authorities and responsibilities."),
                c("CC1.4", "Commitment to competence", "The entity attracts, develops and retains competent people."),
                c("CC1.5", "Accountability", "The entity holds individuals accountable for their control responsibilities."),
            ],
        },
        {
            "key": "CC2", "name": "CC2 - Communication and Information",
            "controls": [
                c("CC2.1", "Relevant information", "The entity obtains and uses relevant, quality information to support internal control."),
                c("CC2.2", "Internal communication", "The entity communicates internal-control information internally."),
                c("CC2.3", "External communication", "The entity communicates relevant information to external parties."),
            ],
        },
        {
            "key": "CC3", "name": "CC3 - Risk Assessment",
            "controls": [
                c("CC3.1", "Objectives", "The entity specifies objectives clearly enough to identify and assess related risks."),
                c("CC3.2", "Risk identification", "The entity identifies and analyses risks to achieving its objectives."),
                c("CC3.3", "Fraud risk", "The entity considers the potential for fraud when assessing risk."),
                c("CC3.4", "Change risk", "The entity identifies and assesses changes that could impact internal control."),
            ],
        },
        {
            "key": "CC4", "name": "CC4 - Monitoring Activities",
            "controls": [
                c("CC4.1", "Ongoing evaluations", "The entity performs ongoing and separate evaluations of its controls."),
                c("CC4.2", "Deficiency communication", "The entity evaluates and communicates control deficiencies for remediation."),
            ],
        },
        {
            "key": "CC5", "name": "CC5 - Control Activities",
            "controls": [
                c("CC5.1", "Control selection", "The entity selects and develops control activities that mitigate risk."),
                c("CC5.2", "Technology controls", "The entity selects and develops general control activities over technology."),
                c("CC5.3", "Policy deployment", "The entity deploys control activities through policies and procedures."),
            ],
        },
        {
            "key": "CC6", "name": "CC6 - Logical and Physical Access Controls",
            "controls": [
                c("CC6.1", "Access security", "Logical access security software and infrastructure protect information assets."),
                c("CC6.2", "User provisioning", "New internal and external users are registered and authorised before access is granted."),
                c("CC6.3", "Least privilege", "Access is granted based on roles and least privilege, and reviewed periodically."),
                c("CC6.4", "Physical access", "Physical access to facilities and assets is restricted to authorised personnel."),
                c("CC6.5", "Asset disposal", "Data and media are securely disposed of when no longer needed."),
                c("CC6.6", "Boundary protection", "The entity protects against external threats at system boundaries."),
                c("CC6.7", "Transmission security", "Information in transit is restricted and protected against unauthorised access."),
                c("CC6.8", "Unauthorised software", "The entity prevents and detects the introduction of unauthorised software."),
            ],
        },
        {
            "key": "CC7", "name": "CC7 - System Operations",
            "controls": [
                c("CC7.1", "Vulnerability management", "Configurations are monitored and vulnerabilities are detected and remediated."),
                c("CC7.2", "Anomaly monitoring", "System components are monitored for anomalies indicative of security events."),
                c("CC7.3", "Event evaluation", "Security events are evaluated to determine whether they are incidents."),
                c("CC7.4", "Incident response", "The entity responds to identified security incidents through a defined programme."),
                c("CC7.5", "Recovery", "The entity recovers from identified security incidents."),
            ],
        },
        {
            "key": "CC8", "name": "CC8 - Change Management",
            "controls": [
                c("CC8.1", "Change management", "Changes to infrastructure, data, software and procedures are authorised, tested and approved."),
            ],
        },
        {
            "key": "CC9", "name": "CC9 - Risk Mitigation",
            "controls": [
                c("CC9.1", "Business disruption", "The entity mitigates risk from business disruptions."),
                c("CC9.2", "Vendor risk", "The entity assesses and manages risks associated with vendors and partners."),
            ],
        },
        {
            "key": "A1", "name": "A1 - Availability",
            "controls": [
                c("A1.1", "Capacity", "Current and future capacity is managed to meet availability commitments."),
                c("A1.2", "Environmental protection", "Environmental protections, backups and recovery infrastructure are maintained."),
                c("A1.3", "Recovery testing", "Recovery plans are tested to support availability commitments."),
            ],
        },
        {
            "key": "C1", "name": "C1 - Confidentiality",
            "controls": [
                c("C1.1", "Confidential info identification", "Confidential information is identified and maintained."),
                c("C1.2", "Confidential info disposal", "Confidential information is disposed of when no longer required."),
            ],
        },
        {
            "key": "PI1", "name": "PI1 - Processing Integrity",
            "controls": [
                c("PI1.1", "Processing objectives", "The entity uses quality information about processing objectives."),
                c("PI1.2", "Input integrity", "Inputs are complete and accurate."),
                c("PI1.3", "Processing integrity", "Processing is complete, accurate and timely."),
                c("PI1.4", "Output integrity", "Outputs are complete, accurate and delivered to the right recipients."),
                c("PI1.5", "Storage integrity", "Stored inputs and outputs are complete and accurate."),
            ],
        },
        {
            "key": "P", "name": "P - Privacy",
            "controls": [
                c("P1.1", "Privacy notice", "The entity provides notice about its privacy practices."),
                c("P2.1", "Choice and consent", "The entity communicates choices available and obtains consent."),
                c("P3.1", "Collection", "Personal information is collected consistently with the privacy notice."),
                c("P3.2", "Explicit consent", "Explicit consent is obtained for sensitive personal information."),
                c("P4.1", "Use", "Personal information is used consistently with the privacy notice."),
                c("P4.2", "Retention", "Personal information is retained only as long as necessary."),
                c("P4.3", "Disposal", "Personal information is securely disposed of."),
                c("P5.1", "Access", "Data subjects can access their personal information."),
                c("P5.2", "Correction", "Data subjects can correct their personal information."),
                c("P6.1", "Disclosure", "Personal information is disclosed only per the privacy notice."),
                c("P6.2", "Authorised disclosure", "Disclosures are made only to authorised parties."),
                c("P6.3", "Disclosure tracking", "Unauthorised disclosures are recorded and addressed."),
                c("P6.4", "Third-party agreements", "Third parties are bound to equivalent privacy commitments."),
                c("P6.5", "Third-party breaches", "Third-party unauthorised disclosures are identified and addressed."),
                c("P6.6", "Breach notification", "Affected parties and authorities are notified of privacy breaches."),
                c("P6.7", "Accounting of disclosures", "The entity accounts for disclosures of personal information."),
                c("P7.1", "Data quality", "Personal information is accurate and complete for its intended use."),
                c("P8.1", "Complaint handling", "The entity manages privacy complaints and disputes."),
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# ISO/IEC 27001:2022 -- Annex A (93 controls, 4 themes)
# ---------------------------------------------------------------------------
ISO = {
    "key": "iso27001",
    "name": "ISO/IEC 27001",
    "version": "2022",
    "authority": "ISO/IEC",
    "description": "Annex A information security controls (organisational, people, physical, technological).",
    "categories": [
        {
            "key": "A5", "name": "A.5 - Organisational controls",
            "controls": [
                c("A.5.1", "Policies for information security", "Define, approve, publish and review information security policies."),
                c("A.5.2", "Information security roles and responsibilities", "Define and allocate security roles and responsibilities."),
                c("A.5.3", "Segregation of duties", "Separate conflicting duties and areas of responsibility."),
                c("A.5.4", "Management responsibilities", "Management requires personnel to apply security per policy."),
                c("A.5.5", "Contact with authorities", "Maintain contact with relevant authorities."),
                c("A.5.6", "Contact with special interest groups", "Maintain contact with security interest groups."),
                c("A.5.7", "Threat intelligence", "Collect and analyse information about security threats."),
                c("A.5.8", "Information security in project management", "Integrate security into project management."),
                c("A.5.9", "Inventory of information and other associated assets", "Maintain an inventory of assets and owners."),
                c("A.5.10", "Acceptable use of information and other associated assets", "Define and enforce acceptable-use rules."),
                c("A.5.11", "Return of assets", "Personnel return organisational assets on change/termination."),
                c("A.5.12", "Classification of information", "Classify information by value and sensitivity."),
                c("A.5.13", "Labelling of information", "Apply labelling procedures per the classification scheme."),
                c("A.5.14", "Information transfer", "Protect information during transfer by all methods."),
                c("A.5.15", "Access control", "Establish and enforce access-control rules."),
                c("A.5.16", "Identity management", "Manage the full life cycle of identities."),
                c("A.5.17", "Authentication information", "Control allocation and management of authentication information."),
                c("A.5.18", "Access rights", "Provision, review and revoke access rights per policy."),
                c("A.5.19", "Information security in supplier relationships", "Manage security risks from supplier products/services."),
                c("A.5.20", "Addressing information security within supplier agreements", "Include security requirements in supplier agreements."),
                c("A.5.21", "Managing information security in the ICT supply chain", "Manage security risks across the ICT supply chain."),
                c("A.5.22", "Monitoring, review and change management of supplier services", "Monitor and review supplier service delivery."),
                c("A.5.23", "Information security for use of cloud services", "Manage security for acquisition and use of cloud services."),
                c("A.5.24", "Incident management planning and preparation", "Plan and prepare for security incident management."),
                c("A.5.25", "Assessment and decision on information security events", "Assess events and decide if they are incidents."),
                c("A.5.26", "Response to information security incidents", "Respond to incidents per documented procedures."),
                c("A.5.27", "Learning from information security incidents", "Use incident lessons to strengthen controls."),
                c("A.5.28", "Collection of evidence", "Identify, collect and preserve evidence."),
                c("A.5.29", "Information security during disruption", "Maintain security during disruption."),
                c("A.5.30", "ICT readiness for business continuity", "Plan ICT continuity based on business objectives."),
                c("A.5.31", "Legal, statutory, regulatory and contractual requirements", "Identify and meet applicable requirements."),
                c("A.5.32", "Intellectual property rights", "Protect intellectual property rights."),
                c("A.5.33", "Protection of records", "Protect records against loss, falsification and unauthorised access."),
                c("A.5.34", "Privacy and protection of PII", "Protect privacy and personally identifiable information."),
                c("A.5.35", "Independent review of information security", "Independently review the security approach at intervals."),
                c("A.5.36", "Compliance with policies, rules and standards", "Regularly review compliance with the security policy set."),
                c("A.5.37", "Documented operating procedures", "Document and make available operating procedures."),
            ],
        },
        {
            "key": "A6", "name": "A.6 - People controls",
            "controls": [
                c("A.6.1", "Screening", "Verify background of candidates before employment."),
                c("A.6.2", "Terms and conditions of employment", "State security responsibilities in employment terms."),
                c("A.6.3", "Information security awareness, education and training", "Provide ongoing security awareness and training."),
                c("A.6.4", "Disciplinary process", "Operate a disciplinary process for security violations."),
                c("A.6.5", "Responsibilities after termination or change of employment", "Define security duties that persist after role change."),
                c("A.6.6", "Confidentiality or non-disclosure agreements", "Use NDAs reflecting information protection needs."),
                c("A.6.7", "Remote working", "Protect information accessed outside organisational premises."),
                c("A.6.8", "Information security event reporting", "Provide a mechanism to report security events."),
            ],
        },
        {
            "key": "A7", "name": "A.7 - Physical controls",
            "controls": [
                c("A.7.1", "Physical security perimeters", "Define perimeters to protect areas holding information."),
                c("A.7.2", "Physical entry", "Protect secure areas with appropriate entry controls."),
                c("A.7.3", "Securing offices, rooms and facilities", "Design and apply physical security for facilities."),
                c("A.7.4", "Physical security monitoring", "Continuously monitor premises for unauthorised access."),
                c("A.7.5", "Protecting against physical and environmental threats", "Protect against physical and environmental threats."),
                c("A.7.6", "Working in secure areas", "Apply measures for working in secure areas."),
                c("A.7.7", "Clear desk and clear screen", "Enforce clear-desk and clear-screen rules."),
                c("A.7.8", "Equipment siting and protection", "Site and protect equipment to reduce risk."),
                c("A.7.9", "Security of assets off-premises", "Protect off-site assets."),
                c("A.7.10", "Storage media", "Manage storage media through its life cycle."),
                c("A.7.11", "Supporting utilities", "Protect equipment from utility failures."),
                c("A.7.12", "Cabling security", "Protect power and telecommunications cabling."),
                c("A.7.13", "Equipment maintenance", "Maintain equipment to ensure availability and integrity."),
                c("A.7.14", "Secure disposal or re-use of equipment", "Verify removal of data before disposal/re-use."),
            ],
        },
        {
            "key": "A8", "name": "A.8 - Technological controls",
            "controls": [
                c("A.8.1", "User endpoint devices", "Protect information on user endpoint devices."),
                c("A.8.2", "Privileged access rights", "Restrict and manage privileged access rights."),
                c("A.8.3", "Information access restriction", "Restrict access to information per access-control policy."),
                c("A.8.4", "Access to source code", "Manage access to source code and development tools."),
                c("A.8.5", "Secure authentication", "Implement secure authentication technologies."),
                c("A.8.6", "Capacity management", "Monitor and tune resource use to meet capacity needs."),
                c("A.8.7", "Protection against malware", "Protect against malware with user awareness and controls."),
                c("A.8.8", "Management of technical vulnerabilities", "Identify and address technical vulnerabilities."),
                c("A.8.9", "Configuration management", "Establish and maintain secure configurations."),
                c("A.8.10", "Information deletion", "Delete information when no longer required."),
                c("A.8.11", "Data masking", "Mask data per policy and applicable requirements."),
                c("A.8.12", "Data leakage prevention", "Apply measures to prevent data leakage."),
                c("A.8.13", "Information backup", "Maintain and test backups per an agreed policy."),
                c("A.8.14", "Redundancy of information processing facilities", "Provide redundancy to meet availability needs."),
                c("A.8.15", "Logging", "Produce, store and review activity logs."),
                c("A.8.16", "Monitoring activities", "Monitor systems and networks for anomalous behaviour."),
                c("A.8.17", "Clock synchronisation", "Synchronise clocks to an approved time source."),
                c("A.8.18", "Use of privileged utility programs", "Restrict and control privileged utility programs."),
                c("A.8.19", "Installation of software on operational systems", "Control software installation on operational systems."),
                c("A.8.20", "Networks security", "Secure and manage networks and network devices."),
                c("A.8.21", "Security of network services", "Identify and manage security of network services."),
                c("A.8.22", "Segregation of networks", "Segregate groups of services and systems on networks."),
                c("A.8.23", "Web filtering", "Manage access to external websites."),
                c("A.8.24", "Use of cryptography", "Define and implement rules for cryptography and key management."),
                c("A.8.25", "Secure development life cycle", "Apply security rules across the development life cycle."),
                c("A.8.26", "Application security requirements", "Identify and approve application security requirements."),
                c("A.8.27", "Secure system architecture and engineering principles", "Apply secure engineering principles."),
                c("A.8.28", "Secure coding", "Apply secure coding principles."),
                c("A.8.29", "Security testing in development and acceptance", "Define and perform security testing."),
                c("A.8.30", "Outsourced development", "Direct and monitor outsourced development."),
                c("A.8.31", "Separation of development, test and production environments", "Separate development, test and production."),
                c("A.8.32", "Change management", "Subject changes to change-management procedures."),
                c("A.8.33", "Test information", "Select, protect and manage test information."),
                c("A.8.34", "Protection of information systems during audit testing", "Plan audit tests to minimise operational disruption."),
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# PCI DSS v4.0.1 -- 12 requirements
# ---------------------------------------------------------------------------
PCI = {
    "key": "pci_dss_v4",
    "name": "PCI DSS",
    "version": "4.0.1",
    "authority": "PCI SSC",
    "description": "Payment Card Industry Data Security Standard v4.0.1 - 12 requirements.",
    "categories": [
        {
            "key": "Req1", "name": "Req 1 - Network Security Controls",
            "controls": [
                c("1.1", "Processes for NSCs", "Processes and mechanisms for network security controls are defined and understood."),
                c("1.2", "NSC configuration", "Network security controls are configured and maintained."),
                c("1.3", "CDE network access", "Network access to and from the cardholder data environment is restricted."),
                c("1.4", "Trusted/untrusted connections", "Connections between trusted and untrusted networks are controlled."),
                c("1.5", "Dual-connected devices", "Risks from devices connected to both untrusted networks and the CDE are mitigated."),
            ],
        },
        {
            "key": "Req2", "name": "Req 2 - Secure Configurations",
            "controls": [
                c("2.1", "Config processes", "Processes and mechanisms for secure configurations are defined and understood."),
                c("2.2", "System configuration", "System components are configured and managed securely."),
                c("2.3", "Wireless configuration", "Wireless environments are configured and managed securely."),
            ],
        },
        {
            "key": "Req3", "name": "Req 3 - Protect Stored Account Data",
            "controls": [
                c("3.1", "Storage processes", "Processes and mechanisms for protecting stored account data are defined."),
                c("3.2", "Minimise storage", "Storage of account data is kept to a minimum."),
                c("3.3", "No SAD after auth", "Sensitive authentication data is not stored after authorisation."),
                c("3.4", "PAN display", "Access to displays of full PAN and copying of PAN is restricted."),
                c("3.5", "PAN protection", "PAN is secured wherever it is stored."),
                c("3.6", "Key protection", "Cryptographic keys protecting stored account data are secured."),
                c("3.7", "Key management", "Key-management processes and procedures are defined and implemented."),
            ],
        },
        {
            "key": "Req4", "name": "Req 4 - Protect Data in Transit",
            "controls": [
                c("4.1", "Transmission processes", "Processes and mechanisms for protecting data in transit are defined."),
                c("4.2", "Strong cryptography", "PAN is protected with strong cryptography during transmission over open networks."),
            ],
        },
        {
            "key": "Req5", "name": "Req 5 - Protect Against Malware",
            "controls": [
                c("5.1", "Malware processes", "Processes and mechanisms for protecting against malware are defined."),
                c("5.2", "Malware prevention", "Malicious software is prevented, or detected and addressed."),
                c("5.3", "Anti-malware upkeep", "Anti-malware mechanisms are active, maintained and monitored."),
                c("5.4", "Anti-phishing", "Anti-phishing mechanisms protect personnel."),
            ],
        },
        {
            "key": "Req6", "name": "Req 6 - Secure Systems and Software",
            "controls": [
                c("6.1", "Development processes", "Processes and mechanisms for secure systems and software are defined."),
                c("6.2", "Secure development", "Bespoke and custom software is developed securely."),
                c("6.3", "Vulnerability management", "Security vulnerabilities are identified and addressed."),
                c("6.4", "Web app protection", "Public-facing web applications are protected against attacks."),
                c("6.5", "Change management", "Changes to system components are managed securely."),
            ],
        },
        {
            "key": "Req7", "name": "Req 7 - Restrict Access by Need to Know",
            "controls": [
                c("7.1", "Access processes", "Processes and mechanisms for restricting access are defined."),
                c("7.2", "Access assignment", "Access to system components and data is defined and assigned appropriately."),
                c("7.3", "Access control system", "Access is managed via an access-control system."),
            ],
        },
        {
            "key": "Req8", "name": "Req 8 - Identify and Authenticate",
            "controls": [
                c("8.1", "Auth processes", "Processes and mechanisms for identification and authentication are defined."),
                c("8.2", "User identification", "User identities and accounts are strictly managed."),
                c("8.3", "Strong authentication", "Strong authentication for users is established and managed."),
                c("8.4", "MFA for CDE", "Multi-factor authentication secures access into the CDE."),
                c("8.5", "MFA configuration", "MFA systems are configured to prevent misuse."),
                c("8.6", "Application/system accounts", "Use of application and system accounts and factors is strictly managed."),
            ],
        },
        {
            "key": "Req9", "name": "Req 9 - Restrict Physical Access",
            "controls": [
                c("9.1", "Physical processes", "Processes and mechanisms for restricting physical access are defined."),
                c("9.2", "Facility access", "Physical access controls manage entry into facilities and systems."),
                c("9.3", "Personnel/visitor access", "Physical access for personnel and visitors is authorised and managed."),
                c("9.4", "Media handling", "Media with cardholder data is stored, distributed and destroyed securely."),
                c("9.5", "POI device protection", "Point-of-interaction devices are protected from tampering and substitution."),
            ],
        },
        {
            "key": "Req10", "name": "Req 10 - Log and Monitor Access",
            "controls": [
                c("10.1", "Logging processes", "Processes and mechanisms for logging and monitoring are defined."),
                c("10.2", "Audit logs", "Audit logs support detection of anomalies and suspicious activity."),
                c("10.3", "Log protection", "Audit logs are protected from destruction and unauthorised modification."),
                c("10.4", "Log review", "Audit logs are reviewed to identify anomalies or suspicious activity."),
                c("10.5", "Log retention", "Audit log history is retained and available for analysis."),
                c("10.6", "Time synchronisation", "Time-synchronisation mechanisms support consistent time settings."),
                c("10.7", "Control failure response", "Failures of critical security controls are detected and responded to promptly."),
            ],
        },
        {
            "key": "Req11", "name": "Req 11 - Test Security Regularly",
            "controls": [
                c("11.1", "Testing processes", "Processes and mechanisms for regularly testing security are defined."),
                c("11.2", "Wireless monitoring", "Wireless access points are identified and monitored."),
                c("11.3", "Vulnerability scanning", "Internal and external vulnerabilities are identified, prioritised and addressed."),
                c("11.4", "Penetration testing", "Internal and external penetration testing is performed and findings corrected."),
                c("11.5", "Intrusion detection", "Network intrusions and unexpected file changes are detected and responded to."),
                c("11.6", "Payment page monitoring", "Unauthorised changes on payment pages are detected and responded to."),
            ],
        },
        {
            "key": "Req12", "name": "Req 12 - Organisational Policies",
            "controls": [
                c("12.1", "Security policy", "A comprehensive information security policy governs asset protection."),
                c("12.2", "Acceptable use", "Acceptable-use policies for end-user technologies are defined and implemented."),
                c("12.3", "Risk management", "Risks to the CDE are formally identified, evaluated and managed."),
                c("12.4", "Compliance management", "PCI DSS compliance is managed."),
                c("12.5", "Scope validation", "PCI DSS scope is documented and validated."),
                c("12.6", "Security awareness", "Security awareness education is an ongoing activity."),
                c("12.7", "Personnel screening", "Personnel are screened to reduce insider-threat risk."),
                c("12.8", "Third-party management", "Risk from third-party service provider relationships is managed."),
                c("12.9", "TPSP support", "Third-party service providers support customer PCI DSS compliance."),
                c("12.10", "Incident response", "Suspected and confirmed incidents impacting the CDE are responded to immediately."),
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# Cross-framework crosswalk (representative starter set -- extend freely)
# Groups the "same" underlying control theme across the three frameworks so a
# single piece of evidence can satisfy multiple standards (Vanta-style).
# ---------------------------------------------------------------------------
CROSSWALK = [
    {"theme": "Access control policy & least privilege",
     "soc2": ["CC6.1", "CC6.3"], "iso27001": ["A.5.15", "A.8.3"], "pci_dss_v4": ["7.1", "7.2"]},
    {"theme": "User provisioning & de-provisioning",
     "soc2": ["CC6.2"], "iso27001": ["A.5.16", "A.5.18"], "pci_dss_v4": ["8.2"]},
    {"theme": "Authentication & MFA",
     "soc2": ["CC6.1"], "iso27001": ["A.5.17", "A.8.5"], "pci_dss_v4": ["8.3", "8.4"]},
    {"theme": "Privileged access management",
     "soc2": ["CC6.3"], "iso27001": ["A.8.2", "A.8.18"], "pci_dss_v4": ["7.2", "8.6"]},
    {"theme": "Encryption of data in transit",
     "soc2": ["CC6.7"], "iso27001": ["A.8.24"], "pci_dss_v4": ["4.2"]},
    {"theme": "Encryption / protection of data at rest",
     "soc2": ["CC6.1"], "iso27001": ["A.8.24"], "pci_dss_v4": ["3.5", "3.6"]},
    {"theme": "Vulnerability management",
     "soc2": ["CC7.1"], "iso27001": ["A.8.8"], "pci_dss_v4": ["6.3", "11.3"]},
    {"theme": "Malware protection",
     "soc2": ["CC6.8"], "iso27001": ["A.8.7"], "pci_dss_v4": ["5.2", "5.3"]},
    {"theme": "Logging & monitoring",
     "soc2": ["CC7.2"], "iso27001": ["A.8.15", "A.8.16"], "pci_dss_v4": ["10.2", "10.4"]},
    {"theme": "Change management",
     "soc2": ["CC8.1"], "iso27001": ["A.8.32"], "pci_dss_v4": ["6.5"]},
    {"theme": "Incident response",
     "soc2": ["CC7.4", "CC7.5"], "iso27001": ["A.5.24", "A.5.26"], "pci_dss_v4": ["12.10"]},
    {"theme": "Vendor / third-party risk",
     "soc2": ["CC9.2"], "iso27001": ["A.5.19", "A.5.20"], "pci_dss_v4": ["12.8", "12.9"]},
    {"theme": "Risk assessment",
     "soc2": ["CC3.1", "CC3.2"], "iso27001": ["A.5.7"], "pci_dss_v4": ["12.3"]},
    {"theme": "Security awareness training",
     "soc2": ["CC1.4"], "iso27001": ["A.6.3"], "pci_dss_v4": ["12.6"]},
    {"theme": "Personnel screening",
     "soc2": ["CC1.4"], "iso27001": ["A.6.1"], "pci_dss_v4": ["12.7"]},
    {"theme": "Physical access control",
     "soc2": ["CC6.4"], "iso27001": ["A.7.1", "A.7.2"], "pci_dss_v4": ["9.2", "9.3"]},
    {"theme": "Secure disposal of media/data",
     "soc2": ["CC6.5"], "iso27001": ["A.7.14", "A.8.10"], "pci_dss_v4": ["9.4"]},
    {"theme": "Backup & availability",
     "soc2": ["A1.2"], "iso27001": ["A.8.13"], "pci_dss_v4": ["12.10"]},
    {"theme": "Information security policy set",
     "soc2": ["CC5.3"], "iso27001": ["A.5.1"], "pci_dss_v4": ["12.1"]},
    {"theme": "Network segmentation / boundary protection",
     "soc2": ["CC6.6"], "iso27001": ["A.8.20", "A.8.22"], "pci_dss_v4": ["1.3", "1.4"]},
]


def count_controls(fw):
    return sum(len(cat["controls"]) for cat in fw["categories"])


def write(name, data):
    path = os.path.abspath(os.path.join(OUT_DIR, name))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


if __name__ == "__main__":
    for fw, fname in [(SOC2, "soc2.json"), (ISO, "iso27001.json"), (PCI, "pci_dss_v4.json")]:
        p = write(fname, fw)
        print(f"  {fw['name']} {fw['version']:<14} {count_controls(fw):>3} controls  ->  {os.path.relpath(p)}")
    p = write("crosswalk.json", {"mappings": CROSSWALK})
    print(f"  Crosswalk {'':<19} {len(CROSSWALK):>3} themes    ->  {os.path.relpath(p)}")
