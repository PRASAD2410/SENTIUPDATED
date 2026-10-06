# Synthetic Criminal Intelligence Dataset Standard

## Master World → Multi-Source Evidence → Knowledge Graph

**Version:** 1.0\
**Scope:** Money laundering, criminal network analysis, cyber fraud /
mule-account detection\
**Backend target:** Python\
**Database target:** MongoDB\
**Output sources:** KYC, banking, CDR, FIR, company registry,
cyber/digital, vehicle/location, evidence\
**Generation strategy:** Master-world-first + case planting + source
rendering + controlled augmentation

------------------------------------------------------------------------

# 1. Core design principle

Do **not** independently generate KYC, bank, CDR, FIR, company and cyber
datasets and then try to join them.

Generate one hidden, internally consistent **Master Synthetic World**
first.

``` text
                         MASTER SYNTHETIC WORLD
                                  |
                +-----------------+-----------------+
                |                 |                 |
             Persons           Entities          Locations
                |                 |                 |
        +-------+-------+    +----+------+          |
        |       |       |    |           |          |
      Phone    ID     Person Account   Company    Address
        |                      |           |
       SIM                   UPI/Card    Vehicle
        |
      IMEI/Device
                |
                v
       SHARED ENTITY REGISTRY
       canonical IDs + mappings
                |
      +---------+---------+---------+---------+---------+
      |         |         |         |         |         |
     KYC       BANK      CDR       FIR     COMPANY    CYBER
      |         |         |         |         |         |
      +---------+---------+---------+---------+---------+
                |
                v
          KNOWLEDGE GRAPH
                |
       +--------+---------+
       |        |         |
      AML     CRIMINAL   CYBER/
              NETWORK    MULE
```

The public datasets are **reference material**, not the identity
backbone.

Use them to learn:

-   column conventions
-   value types
-   distributions
-   transaction/call behavior
-   typologies
-   normal-vs-suspicious ratios
-   realistic categorical values
-   timestamp patterns
-   graph structures

Then generate synthetic records using the shared master world.

------------------------------------------------------------------------

# 2. Three problem domains

The generator must support all three without creating three disconnected
datasets.

## 2.1 Money laundering

Minimum typologies:

-   structuring
-   layering
-   mule networks
-   shell companies
-   rapid movement
-   circular flows
-   pass-through accounts
-   cross-border movement
-   unusual high-value transfers
-   coordinated account activity
-   legitimate high-volume lookalikes

## 2.2 Criminal network analysis

Minimum patterns:

-   communication hub/coordinator
-   broker/bridge between communities
-   dense criminal community
-   shared phone/device
-   shared address
-   repeated meetings
-   coordinated calls
-   travel + meeting + transaction
-   company/director relationships
-   multi-source evidence chain
-   incomplete-evidence cases
-   innocent high-degree decoys

## 2.3 Cyber fraud / mule-account detection

Minimum patterns:

-   phishing
-   account takeover
-   fake investment
-   mule recruitment
-   mule network
-   shared IP/device infrastructure
-   suspicious login followed by transaction
-   victim → mule → layering chain
-   social/email/domain relationships
-   legitimate shared infrastructure lookalikes

------------------------------------------------------------------------

# 3. Source datasets and purpose

  -------------------------------------------------------------------------
  Source                   Purpose                  Generator source
  ------------------------ ------------------------ -----------------------
  `kyc.csv`                Identity and account     Master persons/entities
                           ownership                

  `transactions.csv`       Financial behavior       Accounts + planted
                                                    financial events

  `cdr.csv`                Communication network    Phones/SIMs/devices +
                                                    communication events

  `company_registry.csv`   Ownership/directorship   Persons + companies

  `fir.csv` / FIR text     Unstructured evidence    Cases + selected
                                                    entities/events

  `cyber_events.csv`       IP/device/domain/email   Persons + digital
                           activity                 infrastructure

  `vehicle_events.csv`     Physical corroboration   Persons + vehicles +
                                                    locations

  `locations.csv`          Geographic context       Master locations

  `evidence_index.csv`     Links raw evidence to    Source record IDs
                           source events            

  `ground_truth/*.json`    Hidden evaluation truth  Master + planted cases
  -------------------------------------------------------------------------

------------------------------------------------------------------------

# 4. Global ID rules

IDs must be **unique, stable, opaque and non-sequential where realism
benefits from it**.

Do not expose internal array position as an identity.

Bad:

``` text
P001
P002
P003
```

as the only generation strategy.

Better:

``` text
P-7F2A91
P-B81D04
P-19C4E7
```

Sequential IDs may still be used for technical event IDs if needed.

Recommended:

  Entity        Format
  ------------- -------------------------
  person        `P-<6 hex>`
  phone         `PH-<6 hex>`
  SIM           `SIM-<6 hex>`
  device/IMEI   `DEV-<6 hex>`
  account       `ACC-<8 hex>`
  UPI           generated realistic VPA
  company       `COMP-<6 hex>`
  address       `ADDR-<6 hex>`
  vehicle       `VEH-<6 hex>`
  location      `LOC-<6 hex>`
  tower         `TWR-<6 hex>`
  transaction   `TX-<10 hex>`
  call          `CALL-<10 hex>`
  case          `CASE-<6 hex>`
  FIR           `FIR-<6 hex>`
  evidence      `EV-<10 hex>`

The important requirement is **referential consistency**, not whether an
ID looks random.

------------------------------------------------------------------------

# 5. Master entity registry

The generator must create these before source datasets.

## 5.1 Person

  Field            Type         Required Variation
  ---------------- ---------- ---------- -------------------------------------------
  `person_id`      string            yes unique
  `full_name`      string            yes culturally/geographically varied
  `dob`            date              yes realistic age distribution
  `gender`         enum              yes configurable distribution
  `nationality`    enum              yes configurable
  `occupation`     enum              yes weighted
  `income_band`    enum               no correlated with occupation
  `address_id`     FK                yes shared addresses possible
  `roles`          array             yes usually one/few; suspicious roles planted
  `risk_profile`   internal           no generator-only
  `created_at`     datetime          yes dataset time

### Realism rules

-   Do not make all people the same age.
-   Do not assign equal probability to every occupation.
-   Families can share addresses.
-   Employees can share office addresses.
-   Students can share housing.
-   High-income occupations should not be rare by accident if the
    reference population contains them.
-   A person's accounts, phones and companies must be generated from
    their role/profile.
-   `risk_profile` must not be exported to the model-facing data.

------------------------------------------------------------------------

# 6. Identity / KYC

## `kyc.csv`

  Field                   Type         Required
  ----------------------- ---------- ----------
  `kyc_record_id`         string            yes
  `person_id`             FK                yes
  `name_as_reported`      string            yes
  `date_of_birth`         date              yes
  `national_id`           string            yes
  `passport_id`           string             no
  `phone_as_reported`     string            yes
  `email_as_reported`     string             no
  `address_as_reported`   string            yes
  `occupation`            string            yes
  `employer_name`         string             no
  `kyc_date`              datetime          yes
  `kyc_status`            enum              yes
  `source_id`             string            yes

### Allowed KYC variation

The same person may appear as:

``` text
Rahul Kumar Sharma
Rahul Sharma
R K Sharma
R. K. Sharma
Rahul K Sharma
```

But variation must be controlled. Do not corrupt every record.

Different people with the same name must exist.

Example:

``` text
P-A1B2C3 → Rahul Sharma, DOB 1997-04-12
P-D4E5F6 → Rahul Sharma, DOB 1989-09-21
```

This is essential for entity-resolution testing.

------------------------------------------------------------------------

# 7. Phone / SIM / device

## `phones.csv`

  Field                 Type
  --------------------- -----------
  `phone_id`            string
  `phone_number`        string
  `country_code`        string
  `status`              enum
  `activation_date`     date
  `deactivation_date`   date/null
  `carrier`             string

## `sims.csv`

  Field
  -------------------
  `sim_id`
  `phone_id`
  `subscriber_type`
  `activation_date`
  `status`

## `devices.csv`

  Field
  ----------------
  `device_id`
  `imei`
  `device_type`
  `manufacturer`
  `model`
  `os`
  `first_seen`
  `last_seen`

### Realism

-   One person may own multiple phones.
-   A phone may change SIM.
-   A SIM may move between devices.
-   A device may be shared by multiple people.
-   Shared devices should be rare but intentional.
-   Do not create one phone per person deterministically.
-   IMEI should be valid-format and, if used as a test identifier,
    optionally checksum-valid.

------------------------------------------------------------------------

# 8. Financial accounts

## `accounts.csv`

  Field                  Type
  ---------------------- ------
  `account_id`           
  `bank_id`              
  `account_number`       
  `account_type`         
  `currency`             
  `opened_date`          
  `closed_date`          
  `status`               
  `holder_type`          
  `holder_id`            
  `branch_location_id`   

### Account types

``` text
savings
current
business
salary
wallet
merchant
joint
```

### Realism

Do not give every person the same number of accounts.

Example weighted behavior:

``` text
Most people: 1–2
Some: 3–4
Businesses: 2–8
High-activity entities: potentially more
```

The exact distribution must be configurable and validated rather than
hard-coded as a claim about reality.

------------------------------------------------------------------------

# 9. Transactions

## `transactions.csv`

  Field                Type         Required
  -------------------- ---------- ----------
  `transaction_id`     string            yes
  `timestamp`          datetime          yes
  `from_account_id`    FK                yes
  `to_account_id`      FK                yes
  `from_bank_id`       FK                yes
  `to_bank_id`         FK                yes
  `amount`             decimal           yes
  `currency`           enum              yes
  `payment_method`     enum              yes
  `transaction_type`   enum              yes
  `channel`            enum              yes
  `location_id`        FK                 no
  `merchant_id`        FK                 no
  `source_id`          string            yes
  `record_status`      enum              yes

### Payment methods

``` text
UPI
IMPS
NEFT
RTGS
CARD
WIRE
CHEQUE
CASH
WALLET
```

### Transaction realism

Amounts must **not** be uniform.

Use a mixture of distributions:

``` text
small everyday transactions
medium regular transactions
large business transactions
rare extreme transactions
```

Use different distributions by account type.

Examples:

``` text
salary account → regular salary + normal expenses
merchant → many incoming/outgoing transactions
business → higher volume and larger amounts
student → lower volume
mule → bursts + pass-through behavior
shell company → sparse but structured/high-value flows
```

Do not generate:

``` text
10000, 20000, 30000, 40000...
```

unless a specific scenario requires it.

Use realistic decimal variation.

------------------------------------------------------------------------

# 10. CDR

## `cdr.csv`

  Field                Type         Required
  -------------------- ---------- ----------
  `call_id`            string            yes
  `timestamp`          datetime          yes
  `caller_phone`       FK/value          yes
  `receiver_phone`     FK/value          yes
  `duration_seconds`   integer           yes
  `cell_tower_id`      FK                 no
  `call_type`          enum              yes
  `direction`          enum              yes
  `source_id`          string            yes
  `record_status`      enum              yes

### Critical rule

Do **not** put `person_id` into raw CDR.

The system should infer:

``` text
phone → SIM → device → person
```

through other sources.

### CDR realism

Use temporal behavior:

-   daytime/evening variation
-   weekday/weekend variation
-   occasional long calls
-   many short calls
-   contact frequency differs by relationship
-   family contacts differ from business contacts
-   criminal coordination may show bursts, but not every suspicious case
    should look identical
-   some legitimate users are high-degree hubs

Add controlled:

-   missing tower
-   duplicate record
-   formatting differences
-   incomplete records
-   repeated call records

------------------------------------------------------------------------

# 11. Company registry

## `company_registry.csv`

  Field
  -------------------------
  `company_id`
  `company_name`
  `registration_number`
  `company_type`
  `industry`
  `incorporation_date`
  `status`
  `registered_address_id`
  `bank_account_id`
  `source_id`

## `company_directors.csv`

  Field
  --------------
  `company_id`
  `person_id`
  `role`
  `start_date`
  `end_date`
  `source_id`

### Realism

Create:

-   ordinary small companies
-   legitimate high-volume companies
-   family businesses
-   companies with several directors
-   companies sharing registered addresses
-   a small number of planted shell-like entities

Do not label shell companies in the source dataset.

------------------------------------------------------------------------

# 12. Locations

## `locations.csv`

  Field
  -----------------
  `location_id`
  `location_type`
  `name`
  `city`
  `state`
  `country`
  `latitude`
  `longitude`
  `address_text`
  `source_id`

### Location types

``` text
house
office
hotel
bank_branch
ATM
cell_tower
toll_plaza
crime_scene
warehouse
shop
restaurant
airport
station
```

### Realism

Locations should form a coherent geographic world.

Do not assign random coordinates independently to every event.

Use:

``` text
city → neighborhood → location
```

and travel-time constraints.

------------------------------------------------------------------------

# 13. Vehicles

## `vehicles.csv`

  Field
  -------------------------
  `vehicle_id`
  `registration_number`
  `vehicle_type`
  `make`
  `model`
  `year`
  `owner_person_id`
  `registered_address_id`
  `status`

## `vehicle_events.csv`

  Field
  ---------------
  `event_id`
  `vehicle_id`
  `timestamp`
  `location_id`
  `event_type`
  `source_id`

Vehicle events can corroborate:

``` text
meeting
travel
crime-scene presence
toll movement
warehouse visits
```

------------------------------------------------------------------------

# 14. Cyber / digital data

## `emails.csv`

  Field
  ------------------
  `email_event_id`
  `timestamp`
  `sender_email`
  `receiver_email`
  `subject_hash`
  `domain`
  `ip_id`
  `source_id`

## `domains.csv`

  Field
  -------------------
  `domain_id`
  `domain`
  `registered_date`
  `registrar`
  `status`

## `ip_events.csv`

  Field
  ---------------
  `ip_event_id`
  `timestamp`
  `ip_address`
  `person_id`
  `device_id`
  `event_type`
  `domain_id`
  `source_id`

## `cyber_events.csv`

  Field
  --------------------
  `event_id`
  `timestamp`
  `event_type`
  `source_entity_id`
  `target_entity_id`
  `ip_id`
  `device_id`
  `domain_id`
  `outcome`
  `source_id`

Do not make every cyber event malicious.

------------------------------------------------------------------------

# 15. FIR / unstructured evidence

FIRs must be generated from the master case graph, not independently.

Each FIR should have:

``` text
fir_id
case_id
fir_number
police_station
registration_date
offence_category
complainant
location
narrative_text
source_id
```

The narrative should naturally mention only some known entities.

Example:

> A person known as R K Sharma was observed meeting two associates near
> the warehouse on 12 April. Subsequent financial activity was recorded
> through an account associated with the business.

The text should not directly reveal:

``` text
P001 is coordinator
fraud = true
```

Evidence extraction must discover the relationships.

------------------------------------------------------------------------

# 16. Evidence index

## `evidence_index.csv`

  Field
  ----------------------
  `evidence_id`
  `source_type`
  `source_record_id`
  `case_id`
  `entity_ids`
  `event_ids`
  `evidence_type`
  `source_reliability`
  `created_at`

Evidence types:

``` text
KYC
CDR
BANK_TRANSACTION
FIR_PARAGRAPH
CCTV
COMPANY_RECORD
CYBER_EVENT
VEHICLE_EVENT
INTELLIGENCE_REPORT
```

------------------------------------------------------------------------

# 17. Relationship standard

Relationships should be explicit in the master world.

## Identity

``` text
SAME_AS
ALIAS_OF
REGISTERED_TO
HAS_DOB
LIVES_AT
```

## Communication

``` text
CALLED
SMSED
MESSAGED
USES
OWNS
SIM_IN_DEVICE
LOGGED_IN_FROM
```

## Financial

``` text
TRANSFERRED_TO
SENT_UPI
WITHDREW_AT
HOLDS_ACCOUNT
DIRECTOR_OF
OWNS_COMPANY
PAID_BY_CARD
```

## Physical

``` text
PRESENT_AT
TRAVELLED_TO
OWNS_VEHICLE
SEEN_WITH
```

## Organization

``` text
MEMBER_OF
EMPLOYED_BY
KIN_OF
ASSOCIATE_OF
```

## Case/evidence

``` text
ASSOCIATED_WITH_CASE
MENTIONED_IN
EVIDENCED_BY
SIMILAR_MO
ACCUSED_OF
VICTIM_OF
```

## Inferred/system

``` text
PREDICTED_LINK
PART_OF_PATTERN
ROLE_OF
FLAGGED_BY
```

------------------------------------------------------------------------

# 18. Edge metadata

Every graph edge should support:

``` text
edge_id
source_node_id
target_node_id
edge_type
start_time
end_time
confidence
origin
source_ids
evidence_ids
layer
extractor
extractor_version
source_reliability
review_status
created_at
```

### `origin`

Only:

``` text
observed
asserted
inferred
predicted
```

This is important because the graph must distinguish:

> what the source explicitly says

from:

> what the system inferred.

------------------------------------------------------------------------

# 19. Normal-world generation

Generate the normal population first.

Recommended initial development scale:

``` yaml
persons: 5000
phones: 6000
sims: 6000
devices: 5000
accounts: 7000
companies: 500
locations: 1000
transactions: 200000
cdr_records: 100000
cyber_events: 20000
vehicles: 2500
cases: 100
```

These are engineering targets, not claims about real-world prevalence.

Start with 1--5% of this size while debugging.

------------------------------------------------------------------------

# 20. Do not make the world uniformly random

Use **hierarchical generation**.

``` text
Country
  ↓
State
  ↓
City
  ↓
Neighborhood
  ↓
Address
  ↓
Person
  ↓
Occupation/income
  ↓
Accounts/phones
  ↓
Behavior
```

This creates correlations.

Example:

``` text
Person
  occupation = shop_owner
        ↓
  business account
        ↓
  merchant transactions
        ↓
  shop location
        ↓
  business phone
```

The same person should not randomly receive:

``` text
student
luxury business owner
airport employee
merchant
```

all at once unless the scenario explains it.

------------------------------------------------------------------------

# 21. Behavioral profiles

Create profiles rather than random rows.

Minimum profiles:

``` text
ordinary_person
student
employee
professional
merchant
business_owner
high_net_worth
frequent_traveller
company_director
customer_service_worker
cash_heavy_business
high_volume_legitimate_business
```

Suspicious profiles are generated by **case planting**, not as a
permanent `criminal=true` attribute.

------------------------------------------------------------------------

# 22. Case planting

After the normal world exists:

``` text
1. Select existing entities.
2. Select a case template.
3. Add suspicious events/relationships.
4. Render those events into relevant sources.
5. Add supporting evidence.
6. Add missing evidence where appropriate.
7. Add innocent lookalikes.
8. Record hidden ground truth.
```

This means:

``` text
same person can be:
normal in KYC
normal in company registry
high-risk in financial behavior
frequently communicating with a case entity
mentioned indirectly in FIR
```

This is much more realistic than labeling an entire person as "fraud".

------------------------------------------------------------------------

# 23. Case library

## AML

``` text
ML-01 Structuring
ML-02 Layering
ML-03 Mule network
ML-04 Shell company
ML-05 Rapid movement
ML-06 Circular flow
ML-07 Cross-border
ML-08 Pass-through account
ML-09 Coordinated transfers
ML-10 Legitimate high-volume decoy
```

## Criminal network

``` text
CN-01 Coordinator
CN-02 Broker/bridge
CN-03 Dense community
CN-04 Shared device
CN-05 Shared address
CN-06 Communication coordination
CN-07 Meeting + travel
CN-08 Company relationship network
CN-09 Multi-source case
CN-10 Incomplete evidence
```

## Cyber/mule

``` text
CF-01 Phishing
CF-02 Account takeover
CF-03 Mule recruitment
CF-04 Mule network
CF-05 Shared infrastructure
CF-06 Fake investment
CF-07 Victim → mule → layering
CF-08 Social/email/domain linkage
CF-09 Suspicious login → transaction
CF-10 Legitimate shared infrastructure decoy
```

------------------------------------------------------------------------

# 24. Hidden ground truth

Never expose the planted truth to the model-facing datasets.

Example:

``` json
{
  "case_id": "CASE-A91F22",
  "category": "money_laundering",
  "typology": "layering",
  "core_entities": [
    "P-A1B2C3",
    "P-D4E5F6",
    "ACC-12AB34CD",
    "ACC-91EF2231"
  ],
  "suspicious_events": [
    "TX-1234567890",
    "TX-9876543210"
  ],
  "roles": {
    "coordinator": ["P-A1B2C3"],
    "mule": ["P-D4E5F6"]
  },
  "expected_subgraph": [
    ["ACC-12AB34CD", "TRANSFERRED_TO", "ACC-91EF2231"]
  ],
  "false_positive_entities": [
    "P-XXXXXX"
  ]
}
```

Maintain separate:

``` text
ground_truth/entities.json
ground_truth/relationships.json
ground_truth/patterns.json
ground_truth/cases.json
```

------------------------------------------------------------------------

# 25. Augmentation / corruption strategy

Augmentation must imitate **source-specific imperfections**, not random
damage.

## KYC

Possible:

-   name abbreviations
-   spacing variation
-   missing email
-   address abbreviations
-   phone formatting
-   stale records
-   duplicate records

## Bank

Possible:

-   missing optional location
-   different account-name representation
-   duplicate source record
-   delayed timestamp
-   different transaction descriptions

## CDR

Possible:

-   missing tower
-   duplicate call
-   truncated duration
-   formatting differences
-   incomplete records

## FIR

Possible:

-   aliases
-   partial phone number
-   natural-language variation
-   indirect references
-   spelling variation
-   omitted identifiers

## Company

Possible:

-   abbreviated company name
-   address formatting
-   director name variants
-   stale director record

## Cyber

Possible:

-   shared infrastructure
-   NAT/shared IP
-   missing device ID
-   domain aliases
-   timestamp differences

------------------------------------------------------------------------

# 26. Augmentation rates

Do not apply the same corruption percentage to everything.

Use configuration:

``` yaml
augmentation:
  kyc:
    name_variation: 0.08
    missing_optional: 0.04
    duplicate: 0.01

  banking:
    duplicate: 0.005
    missing_optional: 0.02
    timestamp_variation: 0.01

  cdr:
    missing_tower: 0.05
    duplicate: 0.01
    incomplete_record: 0.01

  fir:
    alias_usage: 0.20
    partial_identifier: 0.10

  company:
    name_variation: 0.05
    address_variation: 0.04
```

These are **starting engineering parameters**. Calibrate them against
the public datasets you inspect.

------------------------------------------------------------------------

# 27. Public dataset calibration

Use public datasets to estimate:

### IBM AML

Study:

-   transaction amounts
-   currency frequency
-   payment formats
-   account degree
-   transaction frequency
-   temporal clustering
-   laundering-pattern structure

### AMLNet / SynthAML

Study:

-   typology structure
-   alert representation
-   transaction histories
-   graph patterns

### NCRB

Study:

-   crime-category vocabulary
-   broad category proportions
-   case terminology

Do not copy real identities.

### Mobility datasets

Study:

-   trip frequency
-   temporal movement
-   location transitions
-   dwell time

### Enron / communication datasets

Study:

-   degree distributions
-   communication frequency
-   hub behavior
-   community structure

### Social datasets

Study:

-   community sizes
-   clustering
-   degree distribution

The goal is **distribution matching**, not record copying.

------------------------------------------------------------------------

# 28. Smart realism strategies

## Strategy 1 --- Correlated generation

Do not sample every field independently.

``` text
occupation
    ↓
income
    ↓
account type
    ↓
transaction behavior
    ↓
location behavior
```

## Strategy 2 --- Heavy-tailed networks

Communication and transaction networks should not be perfectly uniform.

Have:

-   many low-degree nodes
-   fewer medium-degree nodes
-   very few hubs

But include legitimate hubs as decoys.

## Strategy 3 --- Temporal causality

Events should make chronological sense.

Bad:

``` text
account opened after transaction
```

Better:

``` text
KYC
 ↓
account opened
 ↓
phone activated
 ↓
transaction
 ↓
follow-up transfer
```

## Strategy 4 --- Geographic consistency

Do not teleport people.

Use travel-time constraints.

## Strategy 5 --- Source disagreement

Different sources should contain different views of the same world.

## Strategy 6 --- Missing evidence

Some cases should have incomplete evidence.

## Strategy 7 --- False positives

Plant legitimate entities that resemble suspicious entities.

## Strategy 8 --- Same-name collisions

Several people can share names.

## Strategy 9 --- Shared infrastructure

Families, companies, hostels and offices can legitimately share
phones/IPs/addresses.

## Strategy 10 --- Case overlap

A person can appear in multiple cases.

This prevents every case from becoming an isolated connected component.

------------------------------------------------------------------------

# 29. Validation requirements

The generator must automatically validate:

### Referential integrity

Every:

``` text
account
phone
company
vehicle
location
transaction
call
evidence
```

must point to an existing entity where required.

### Temporal integrity

Check:

``` text
account_opened <= transaction_time
phone_activation <= call_time
company_registration <= company_event
```

### Graph integrity

Check that planted cases actually exist in the generated graph.

### Ground truth integrity

Every ground-truth event must exist in the source data.

### Distribution integrity

Report:

``` text
age distribution
occupation distribution
account count distribution
transaction amount distribution
transaction degree distribution
call degree distribution
company size
location density
missingness
duplicate rate
case prevalence
```

### Reproducibility

Same:

``` text
seed + configuration + generator version
```

must produce the same dataset.

Store:

``` text
generator_version
seed
config_hash
dataset_hash
creation_timestamp
```

------------------------------------------------------------------------

# 30. Recommended repository structure

``` text
synthetic_world/
│
├── config/
│   ├── world.yaml
│   ├── distributions.yaml
│   ├── cases.yaml
│   └── augmentation.yaml
│
├── master/
│   ├── persons.csv
│   ├── phones.csv
│   ├── sims.csv
│   ├── devices.csv
│   ├── accounts.csv
│   ├── companies.csv
│   ├── addresses.csv
│   ├── vehicles.csv
│   └── relationships.csv
│
├── generators/
│   ├── persons.py
│   ├── financial.py
│   ├── cdr.py
│   ├── kyc.py
│   ├── company.py
│   ├── fir.py
│   ├── cyber.py
│   ├── vehicle.py
│   └── augmentation.py
│
├── cases/
│   ├── aml.py
│   ├── criminal_network.py
│   └── cyber_fraud.py
│
├── sources/
│   ├── kyc/
│   ├── banking/
│   ├── cdr/
│   ├── fir/
│   ├── company/
│   ├── cyber/
│   └── vehicle/
│
├── ground_truth/
│   ├── cases.json
│   ├── entities.json
│   ├── relationships.json
│   └── patterns.json
│
└── validation/
    ├── report.json
    └── distributions.json
```

------------------------------------------------------------------------

# 31. Generation pipeline

``` text
CONFIG
  ↓
NORMAL MASTER WORLD
  ↓
PERSON PROFILES
  ↓
ENTITIES
  ↓
RELATIONSHIPS
  ↓
LOCATIONS
  ↓
NORMAL EVENTS
  ↓
CASE PLANNER
  ↓
PLANT CASES
  ↓
GENERATE HIDDEN GROUND TRUTH
  ↓
RENDER SOURCE DATASETS
  ↓
SOURCE-SPECIFIC AUGMENTATION
  ↓
VALIDATION
  ↓
EXPORT CSV/JSON/TXT
  ↓
ENTITY RESOLUTION
  ↓
MONGODB
  ↓
KNOWLEDGE GRAPH
```

------------------------------------------------------------------------

# 32. System prompt for the dataset generator

Copy the following as the **system prompt** for the generator model.

------------------------------------------------------------------------

## SYSTEM PROMPT

You are a senior synthetic-data architect specializing in financial
crime, criminal intelligence, entity resolution, graph analytics and
cyber-fraud datasets.

Your task is to design and/or generate a **large, realistic, internally
consistent synthetic investigation world** for:

1.  Money laundering detection
2.  Criminal network analysis
3.  Cyber fraud and mule-account detection

### Core principle

NEVER independently generate the KYC, banking, CDR, FIR, company, cyber
and vehicle datasets and then randomly join them.

First create a hidden **Master Synthetic World** containing canonical
entities and relationships.

Then render that world into multiple source-specific datasets.

The architecture is:

``` text
MASTER WORLD
    ↓
SHARED ENTITY REGISTRY
    ↓
KYC / BANK / CDR / FIR / COMPANY / CYBER / VEHICLE
    ↓
KNOWLEDGE GRAPH
```

### Required entity classes

Support:

-   Person
-   Phone
-   SIM
-   Device/IMEI
-   Identity document
-   Address
-   Bank
-   Bank account
-   UPI ID
-   Card
-   Wallet
-   Company
-   Vehicle
-   Location
-   Case
-   FIR
-   Offence
-   Incident
-   Call
-   Transaction
-   Meeting
-   Travel event
-   Cyber event
-   Email
-   IP
-   Domain
-   URL
-   Social account
-   Evidence

### Required relationship classes

Support:

-   SAME_AS
-   ALIAS_OF
-   REGISTERED_TO
-   LIVES_AT
-   CALLED
-   MESSAGED
-   USES
-   OWNS
-   SIM_IN_DEVICE
-   LOGGED_IN_FROM
-   TRANSFERRED_TO
-   SENT_UPI
-   WITHDREW_AT
-   HOLDS_ACCOUNT
-   DIRECTOR_OF
-   OWNS_COMPANY
-   PRESENT_AT
-   TRAVELLED_TO
-   OWNS_VEHICLE
-   SEEN_WITH
-   MEMBER_OF
-   EMPLOYED_BY
-   KIN_OF
-   ASSOCIATE_OF
-   ASSOCIATED_WITH_CASE
-   MENTIONED_IN
-   EVIDENCED_BY
-   ACCUSED_OF
-   VICTIM_OF

### Realism rules

1.  Do not make records uniformly random.
2.  Do not make IDs, names, timestamps, amounts or relationships
    artificially sequential unless technically necessary.
3.  Use weighted distributions.
4.  Use correlated attributes.
5.  Use realistic temporal dependencies.
6.  Use realistic geographic dependencies.
7.  Use heavy-tailed network structures where appropriate.
8.  Create legitimate high-degree/high-volume entities as false-positive
    controls.
9.  Create same-name different-person cases.
10. Allow legitimate shared phones, devices, addresses and IPs.
11. Allow one person to have multiple accounts/devices.
12. Allow accounts/devices to change ownership where the source model
    supports it.
13. Do not label a person as criminal in the source data.
14. Do not expose case truth to model-facing data.
15. Keep hidden ground truth separately.
16. Use source-specific corruption rather than universal random
    corruption.
17. Maintain referential integrity.
18. Maintain temporal consistency.
19. Maintain graph consistency.

### Required case typologies

Money laundering:

-   structuring
-   layering
-   mule network
-   shell company
-   rapid movement
-   circular flow
-   pass-through accounts
-   cross-border flow
-   coordinated transfers
-   legitimate high-volume decoy

Criminal network:

-   coordinator
-   broker/bridge
-   dense community
-   shared device
-   shared address
-   communication coordination
-   meeting/travel chain
-   company/director network
-   multi-source case
-   incomplete evidence

Cyber/mule:

-   phishing
-   account takeover
-   mule recruitment
-   mule network
-   shared IP/device infrastructure
-   fake investment
-   victim-to-mule-to-layering chain
-   domain/email/social linkage
-   suspicious login followed by transaction
-   legitimate shared infrastructure decoy

### Source rendering

Generate separate source datasets.

Raw CDR must contain phone-level evidence, not canonical person IDs.

Raw bank data must contain account-level evidence, not hidden case
labels.

FIR text must be natural language and must not directly state system
ground truth.

KYC must contain realistic identity attributes and controlled variation.

Company records must represent ownership/directorship.

Cyber records must represent digital infrastructure and events.

### Entity resolution challenge

Create controlled variation such as:

``` text
Rahul Kumar Sharma
Rahul Sharma
R K Sharma
R. K. Sharma
```

but do not corrupt everything.

Create same-name different-person examples where DOB, phone, address or
other evidence distinguishes them.

### Ground truth

For every planted case, maintain hidden ground truth containing:

-   case_id
-   category
-   typology
-   core entities
-   suspicious events
-   suspicious relationships
-   expected roles
-   expected subgraph
-   false-positive entities
-   missing evidence intentionally introduced

Never put these fields in the model-facing source datasets.

### Generation phases

Always follow:

1.  Define configuration.
2.  Generate normal population.
3.  Generate normal entities.
4.  Generate normal relationships.
5.  Generate normal events.
6.  Plant investigation cases using existing entities.
7.  Add supporting evidence.
8.  Add decoys and incomplete evidence.
9.  Generate hidden ground truth.
10. Render source datasets.
11. Apply source-specific augmentation.
12. Validate.
13. Export.

### Validation

Before declaring the dataset complete, check:

-   all foreign keys resolve
-   all timestamps are valid
-   event order is plausible
-   all planted cases exist
-   all ground-truth events exist
-   no unintended broken references
-   distributions are non-degenerate
-   suspicious patterns are not trivially obvious
-   legitimate lookalikes exist
-   same-name collisions exist
-   missingness is controlled
-   duplicates are controlled
-   same seed produces reproducible output

### Output

When asked to generate data, return:

1.  configuration
2.  master entity tables
3.  source schemas
4.  generation logic
5.  case templates
6.  augmentation rules
7.  hidden ground-truth structure
8.  validation report
9.  generated sample records

When generating actual files, preserve the exact schema defined by the
data contract.

Do not silently add columns.

Do not silently rename columns.

Do not create hidden labels in model-facing datasets.

If a requested field would leak ground truth, place it in the hidden
ground-truth dataset instead.

------------------------------------------------------------------------

# 33. Recommended first implementation

Do not immediately generate millions of records.

Use three stages.

## Stage A --- Connected proof

``` text
50 persons
75 accounts
50 phones
20 companies
1000 transactions
500 calls
10 cases
```

Prove every source connects.

## Stage B --- Development dataset

``` text
500–1000 persons
10000–50000 transactions
10000–25000 calls
50–100 companies
30–50 cases
```

Run entity resolution and graph algorithms.

## Stage C --- Benchmark dataset

Scale using configuration:

``` text
5000+ persons
100000–500000 transactions
100000+ calls
hundreds of companies
100+ cases
```

Only scale after validation passes.

------------------------------------------------------------------------

# 34. Definition of "good dataset"

The dataset is good only if all of these are true:

``` text
[ ] One shared master world
[ ] Every source has its own realistic schema
[ ] All cross-source relationships are recoverable
[ ] Raw sources do not expose canonical IDs unnecessarily
[ ] Same-name entities exist
[ ] Legitimate shared infrastructure exists
[ ] Normal users dominate
[ ] Suspicious cases are planted into the normal world
[ ] Multiple typologies exist
[ ] Cases overlap
[ ] Some evidence is missing
[ ] Some evidence is noisy
[ ] Temporal order is meaningful
[ ] Geographic behavior is coherent
[ ] Transaction and communication networks are non-uniform
[ ] False positives exist
[ ] Hidden ground truth exists
[ ] Generator is reproducible
[ ] Automated validation exists
[ ] Public datasets are used for calibration, not copied
```

## Final rule

**Generate a realistic world first. Plant a small number of criminal
narratives into that world. Render each narrative independently into
multiple source systems. Add realistic source noise. Keep the ground
truth hidden.**

That produces a dataset on which entity resolution, graph construction,
suspicious-subgraph detection, role discovery and evidence-based
investigation can actually be evaluated.
