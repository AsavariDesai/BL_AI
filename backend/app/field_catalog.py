"""Canonical field catalogs, one per document type.

Layouts and labels differ between companies, but the business fields for a given
document type are fixed. Every extractor maps a specific document onto these
canonical keys. Field keys are unique across catalogs (``hs_code`` is shared on
purpose — same meaning in both).

Public API:
    CATALOGS[doc_type]          -> list of field specs
    catalog(doc_type)           -> same
    field_keys(doc_type)        -> ordered list of keys
    groups(doc_type)            -> ordered list of group names
    get_field(key)              -> the spec for a key (any doc type)
    DOC_TYPES                   -> ["bill_of_lading", "shipping_bill"]

Back-compat: ``FIELD_CATALOG`` / ``FIELD_KEYS`` still refer to the BL catalog.
"""
from __future__ import annotations

BILL_OF_LADING: list[dict] = [
    # ---------------------------------------------------------------- Identity
    {"key": "document_type", "label": "Document Type", "group": "Identity", "type": "text",
     "aliases": ["bill of lading", "combined transport bill of lading",
                 "multimodal transport bill of lading", "liner bill of lading",
                 "sea waybill", "seaway bl"],
     "example": "Combined Transport Bill of Lading"},
    {"key": "bl_number", "label": "B/L Number", "group": "Identity", "type": "text",
     "aliases": ["b/l no", "bl no", "b/l number", "bill of lading no", "document no"],
     "example": "181142608002"},
    {"key": "booking_number", "label": "Booking Number", "group": "Identity", "type": "text",
     "aliases": ["booking no", "booking ref", "booking reference"], "example": ""},
    {"key": "reference_number", "label": "Reference Number", "group": "Identity", "type": "text",
     "aliases": ["reference no", "ref no", "shipper's ref", "export references"], "example": ""},
    {"key": "carrier", "label": "Carrier", "group": "Identity", "type": "text",
     "aliases": ["carrier", "as carrier", "the carrier", "shipping line"],
     "example": "LMT Container Lines PVT LTD"},
    {"key": "issued_by_agent", "label": "Signed / Issued By (Agent)", "group": "Identity",
     "type": "text",
     "aliases": ["signed for the carrier", "as agents",
                 "signed for and authority of the master", "signed obo master", "as agent"],
     "example": "LMT Container Lines PVT LTD, As Agents"},

    # ---------------------------------------------------------------- Parties
    {"key": "shipper", "label": "Shipper", "group": "Parties", "type": "block",
     "aliases": ["shipper", "shipper/exporter", "consignor"],
     "example": "BLUEWAVE EXIM, ... HYDERABAD 500032"},
    {"key": "shipper_name", "label": "Shipper — Name", "group": "Parties", "type": "text",
     "aliases": ["shipper name", "shipper", "exporter name"],
     "example": "GREINER BIO-ONE GMBH"},
    {"key": "shipper_addr", "label": "Shipper — Address", "group": "Parties", "type": "block",
     "aliases": ["shipper address", "exporter address"],
     "example": "MAYBACHSTR. 2, 72636 FRICKENHAUSEN"},
    {"key": "shipper_state", "label": "Shipper — State", "group": "Parties", "type": "text",
     "aliases": ["shipper state", "state"], "example": "GERMANY"},
    {"key": "consignee", "label": "Consignee", "group": "Parties", "type": "block",
     "aliases": ["consignee", "consigned to order of", "consigned to order", "to order of"],
     "example": "GREEN GOLD GLOBAL FZC LLC, ... AJMAN UAE"},
    {"key": "consignee_nm", "label": "Consignee — Name", "group": "Parties", "type": "text",
     "aliases": ["consignee name", "consignee"], "example": "JAIN BIOLOGICALS (P) LTD."},
    {"key": "consignee_addr", "label": "Consignee — Address", "group": "Parties", "type": "block",
     "aliases": ["consignee address"],
     "example": "S.C.O: 77-78, 2ND FLOOR, SWASTIK VIHAR, 134109 PANCHKULA"},
    {"key": "consignee_state", "label": "Consignee — State", "group": "Parties", "type": "text",
     "aliases": ["consignee state", "state"], "example": "HARYANA"},
    {"key": "notify_party", "label": "Notify Party", "group": "Parties", "type": "block",
     "aliases": ["notify party", "notify party 1", "notify address", "notify"],
     "example": "SAME AS CONSIGNEE"},
    {"key": "notify_name", "label": "Notify — Name", "group": "Parties", "type": "text",
     "aliases": ["notify name", "notify party name"], "example": "SAME AS CNEE"},
    {"key": "notify_addr", "label": "Notify — Address", "group": "Parties", "type": "block",
     "aliases": ["notify address"], "example": ""},
    {"key": "notify_state", "label": "Notify — State", "group": "Parties", "type": "text",
     "aliases": ["notify state", "state"], "example": ""},
    {"key": "notify_party_2", "label": "Notify Party 2", "group": "Parties", "type": "block",
     "aliases": ["notify party 2", "second notify party", "also notify"], "example": ""},
    {"key": "delivery_agent", "label": "Delivery / Discharge Agent", "group": "Parties",
     "type": "block",
     "aliases": ["delivery agent address", "delivery agent", "discharge port agents",
                 "destination agent", "port agent"],
     "example": "LMT CONTAINER SHIPPING LLC, ... DUBAI, UAE"},
    {"key": "forwarding_agent", "label": "Forwarding Agent", "group": "Parties", "type": "block",
     "aliases": ["forwarding agent", "freight forwarder", "forwarder"], "example": ""},

    # ---------------------------------------------------------------- Routing
    {"key": "pre_carriage_by", "label": "Pre-carriage By", "group": "Routing", "type": "text",
     "aliases": ["pre-carriage by", "precarried by", "precarriage by"], "example": ""},
    {"key": "vessel_and_voyage", "label": "Vessel / Voyage", "group": "Routing", "type": "text",
     "aliases": ["vessel/voyage", "vessel voyage", "ocean vessel", "vessel", "vessel/voy"],
     "example": "ARYA BHUM / 2630"},
    {"key": "place_of_receipt", "label": "Place of Receipt", "group": "Routing", "type": "text",
     "aliases": ["place of receipt", "place of receipt by pre-carrier", "received at"],
     "example": "NHAVA SHEVA"},
    {"key": "port_of_loading", "label": "Port of Loading", "group": "Routing", "type": "text",
     "aliases": ["port of loading", "pol", "loading port"], "example": "NHAVA SHEVA"},
    {"key": "port_of_discharge", "label": "Port of Discharge", "group": "Routing", "type": "text",
     "aliases": ["port of discharge", "pod", "discharge port"], "example": "KHOR FAKKAN"},
    {"key": "place_of_delivery", "label": "Place of Delivery", "group": "Routing", "type": "text",
     "aliases": ["place of delivery", "final place of delivery", "delivery place"],
     "example": "KHOR FAKKAN"},
    {"key": "final_destination", "label": "Final Destination / On-carriage", "group": "Routing",
     "type": "text",
     "aliases": ["final destination", "for on carriage to", "onward inland routing",
                 "for delivery to"], "example": ""},

    # ---------------------------------------------------------------- Cargo
    {"key": "container_and_seal_numbers", "label": "Container & Seal Numbers", "group": "Cargo",
     "type": "list",
     "aliases": ["container no", "container no./seal no", "container no. / seal no",
                 "marks and nos/container no", "seal no"],
     "example": "SEGU9658877 / 40' HRF / Seal 002456"},
    {"key": "total_containers", "label": "Total Number of Containers", "group": "Cargo",
     "type": "text",
     "aliases": ["total number of containers", "total containers", "no. of containers"],
     "example": "1 X 40' HRF"},
    {"key": "marks_and_numbers", "label": "Marks & Numbers", "group": "Cargo", "type": "block",
     "aliases": ["marks and numbers", "marks & numbers", "marks and nos", "shipping marks"],
     "example": "N/M"},
    {"key": "number_and_kind_of_packages", "label": "Number & Kind of Packages", "group": "Cargo",
     "type": "text",
     "aliases": ["number and kind of packages", "no. of pkgs", "number of packages",
                 "kind of packages", "quantity", "packages"],
     "example": "1470 BAGS (20KG MESH BAGS)"},
    {"key": "description_of_goods", "label": "Description of Goods", "group": "Cargo",
     "type": "block",
     "aliases": ["description of goods", "description of packages and goods",
                 "goods description", "said to contain"],
     "example": "INDIAN FRESH ONION"},
    {"key": "hs_code", "label": "HS Code", "group": "Cargo", "type": "text",
     "aliases": ["hs code", "h.s. code", "hs no", "harmonized code"], "example": "07031019"},
    {"key": "gross_weight", "label": "Gross Weight", "group": "Cargo", "type": "quantity",
     "aliases": ["gross weight", "gross wt", "gross weight (mts)"], "example": "29500.000 KGS"},
    {"key": "net_weight", "label": "Net Weight", "group": "Cargo", "type": "quantity",
     "aliases": ["net weight", "net wt", "net weight (mts)"], "example": "29400.000 KGS"},
    {"key": "measurement_cbm", "label": "Measurement (CBM)", "group": "Cargo", "type": "quantity",
     "aliases": ["measurement", "cbm", "measure", "volume"], "example": "65.254 CBM"},

    # ---------------------------------------------------------- Commercial
    {"key": "freight_terms", "label": "Freight Terms", "group": "Commercial", "type": "text",
     "aliases": ["freight prepaid", "freight collect", "freight payable", "prepaid", "collect"],
     "example": "FREIGHT PREPAID"},
    {"key": "freight_payable_at", "label": "Freight Payable At", "group": "Commercial",
     "type": "text", "aliases": ["freight payable at", "payable at"], "example": "NHAVA SHEVA"},
    {"key": "movement_type", "label": "Movement Type", "group": "Commercial", "type": "text",
     "aliases": ["fcl/fcl", "lcl/lcl", "cy/cy", "cy/cfs", "fcl", "movement"],
     "example": "FCL/FCL, CY/CY"},
    {"key": "incoterms", "label": "Incoterms / Shipping Terms", "group": "Commercial",
     "type": "text",
     "aliases": ["incoterms", "shipping terms", "delivery terms", "cfr", "fob", "cif"],
     "example": "CFR HOUSTON PORT, USA (INCOTERMS 2020)"},
    {"key": "number_of_original_bls", "label": "Number of Original B/Ls", "group": "Commercial",
     "type": "text",
     "aliases": ["number of original", "number of original b/ls", "no. of original bs/l",
                 "originals"], "example": "THREE / 3"},
    {"key": "shipped_on_board_date", "label": "Shipped On Board Date", "group": "Commercial",
     "type": "date",
     "aliases": ["shipped on board", "on board", "shipped on board date", "laden on board"],
     "example": "14 AUG 2026"},
    {"key": "place_and_date_of_issue", "label": "Place & Date of Issue", "group": "Commercial",
     "type": "text",
     "aliases": ["place and date of issue", "place of issue", "date of issue", "issued at"],
     "example": "NHAVA SHEVA, 14 AUG 2026"},

    # ---------------------------------------------------- Reference documents
    {"key": "invoice_number_and_date", "label": "Invoice No. & Date", "group": "References",
     "type": "text",
     "aliases": ["invoice no", "invoice number", "inv no", "commercial invoice"],
     "example": "BW/001/26-27 DT. 08.08.2026"},
    {"key": "shipping_bill_number_and_date", "label": "Shipping Bill No. & Date",
     "group": "References", "type": "text",
     "aliases": ["sb no", "shipping bill no", "shipping bill number"],
     "example": "5778867 DT. 08.08.2026"},
    {"key": "iec_code", "label": "IEC Code", "group": "References", "type": "text",
     "aliases": ["iec no", "iec code", "iec"], "example": "0388086301"},
    {"key": "gstin", "label": "GSTIN (without state code)", "group": "References",
     "type": "text",
     "aliases": ["gstin", "gst no", "gstn", "gst number", "gst"],
     "example": "AAAFJ1721H2ZQ"},
    {"key": "lc_number", "label": "LC / Documentary Credit No.", "group": "References",
     "type": "text",
     "aliases": ["documentary credit number", "l/c no", "lc no", "letter of credit"],
     "example": "ILC26P0000012 DATED 260612"},
    {"key": "purchase_order_number", "label": "Purchase Order No.", "group": "References",
     "type": "text",
     "aliases": ["po#", "po no", "purchase order", "p.o. number"], "example": "10134595"},
]

# ---------------------------------------------------------------------------
# Shipping Bill (Indian customs export declaration). One SB is the master that
# many Bills of Lading are linked under.
SHIPPING_BILL: list[dict] = [
    {"key": "sb_number", "label": "SB Number", "group": "Identity", "type": "text",
     "aliases": ["shipping bill no", "sb no", "s/b no", "shipping bill number", "sb number"],
     "example": "5778867"},
    {"key": "sb_field_location", "label": "Port Code", "group": "Identity",
     "type": "text",
     "aliases": ["field location", "location code", "port code", "customs location",
                 "sb field location"], "example": "INNSA1"},
    {"key": "sb_date", "label": "SB Date", "group": "Identity", "type": "date",
     "aliases": ["sb date", "shipping bill date", "sb.date", "s/b date"],
     "example": "08.08.2026"},
    {"key": "cin_number", "label": "CIN No.", "group": "Identity", "type": "text",
     "aliases": ["cin no", "cin number", "c.i.n", "cargo identification number"],
     "example": "26PCEG07033580219700"},
    {"key": "cin_date", "label": "CIN Date", "group": "Identity", "type": "date",
     "aliases": ["cin dt", "cin date", "c.i.n date"], "example": "03-JUL-26"},

    {"key": "sb_packages", "label": "SB Packages", "group": "Shipment", "type": "text",
     "aliases": ["no of packages", "number of packages", "sb pkg", "packages", "total packages"],
     "example": "1470"},
    {"key": "sb_gross_weight", "label": "SB Gross Weight", "group": "Shipment", "type": "quantity",
     "aliases": ["gross weight", "sb gross wt", "total gross weight", "gross wt"],
     "example": "29500.000 KGS"},
    {"key": "marks_and_numbers", "label": "Marks & Numbers", "group": "Shipment", "type": "block",
     "aliases": ["marks & numbers", "marks and numbers", "marks no", "shipping marks"],
     "example": "AS PER INVOICE"},
    {"key": "invoice_amount", "label": "Invoice Amount", "group": "Shipment", "type": "quantity",
     "aliases": ["invoice amount", "inv amt", "invoice value"], "example": "44795.28"},
    {"key": "currency", "label": "Currency", "group": "Shipment", "type": "text",
     "aliases": ["currency", "ccy", "curr"], "example": "USD"},
    {"key": "leo_date", "label": "LEO Date", "group": "Shipment", "type": "date",
     "aliases": ["leo date", "let export order date", "leo", "let export date"],
     "example": "14.08.2026"},
    {"key": "leo_number", "label": "LEO No.", "group": "Shipment", "type": "text",
     "aliases": ["leo no", "leo no.", "let export order no", "leo number"],
     "example": "1/6"},
    {"key": "sb_destination", "label": "Final Destination", "group": "Shipment", "type": "text",
     "aliases": ["destination", "sb dest", "port of final destination",
                 "country of final destination", "final destination", "port of destination"],
     "example": "USHOU (Houston), UNITED STATES"},
    {"key": "nature_of_cargo", "label": "Nature of Cargo", "group": "Shipment", "type": "text",
     "aliases": ["nature of cargo", "cargo nature", "type of cargo"],
     "example": "PACKAGED"},

    {"key": "exporter_name", "label": "Exporter Name", "group": "Parties", "type": "text",
     "aliases": ["exporter name", "exporter", "name of exporter", "exporter's name"],
     "example": "KIRLOSKAR FERROUS INDUSTRIES LTD"},
    {"key": "shipper_address", "label": "Exporter Address", "group": "Parties", "type": "block",
     "aliases": ["shipper address", "exporter address", "address of exporter",
                 "exporter's name & address"],
     "example": "B 13 MIDC, BARAMATI, MAHARASHTRA"},
    {"key": "consignee_name", "label": "Consignee / Buyer Name", "group": "Parties", "type": "text",
     "aliases": ["consignee name", "consignee", "name of consignee", "buyer name",
                 "consignee name & address"],
     "example": "BAOWIN STEEL LLC"},
    {"key": "consignee_address", "label": "Consignee / Buyer Address", "group": "Parties",
     "type": "block",
     "aliases": ["consignee address", "buyer address", "consignee name & address"],
     "example": "2901 WILCREST ROAD, SUITE 235, HOUSTON, TX 77042, USA"},
    {"key": "shipper_code", "label": "Shipper Code / IEC", "group": "Parties", "type": "text",
     "aliases": ["shipper code", "iec", "ie code", "iec code", "exporter code", "iec/br"],
     "example": "0797000119"},
    {"key": "gstin", "label": "GST", "group": "Parties", "type": "text",
     "aliases": ["gst", "gstin", "gstin/type", "gst no"], "example": "33AAICS1940E1ZO"},

    {"key": "cargo_description", "label": "Description", "group": "Cargo", "type": "block",
     "aliases": ["cargo description", "description of goods", "cargo des", "goods description",
                 "item description"],
     "example": "TUBES, PIPES OF IRON OR STEEL"},
    {"key": "hs_code", "label": "HS Code", "group": "Cargo", "type": "text",
     "aliases": ["hs code", "h.s. code", "hs no", "harmonized code", "ritc", "cth"],
     "example": "73043919"},
]

# ---------------------------------------------------------------------------
# When a Shipping Bill is uploaded and linked to one specific BL (the
# "BL-first" flow — see service.link_shipping_bill_to_bl), only this fixed,
# curated subset of its fields is surfaced/exported against that BL — a
# single field set, not a choice between a "Key Details" and "All Details"
# option. Everything else on the SB is still extracted and still fully
# visible on the SB's own record — this list only governs what's
# shown/exported *alongside a linked BL*.
SB_EXPORT_FIELDS: list[tuple[str, str]] = [
    ("sb_number", "Shipping Bill No."),
    ("sb_date", "Shipping Bill Date"),
    ("cin_number", "CIN No."),
    ("cin_date", "CIN Date"),
    ("sb_packages", "No. of Packages"),
    ("sb_gross_weight", "Weight"),
    ("sb_field_location", "Port of Loading"),
    ("sb_destination", "Port of Discharge"),
    ("shipper_code", "IEC/BR"),
    ("marks_and_numbers", "Marks & Numbers"),
    ("cargo_description", "Description"),
    ("hs_code", "HS Code"),
    ("exporter_name", "Exporter"),
    ("shipper_address", "Shipper"),
    ("leo_number", "LEO No."),
    ("leo_date", "LEO Date"),
    ("gstin", "GST"),
    ("nature_of_cargo", "Nature of Cargo"),
    ("invoice_amount", "Invoice Amount"),
    ("currency", "Currency"),
]

# ---------------------------------------------------------------------------
# Master BL (Import category). Modeled on the Ocean Network Express ("ONE")
# Sea Waybill / Master Bill of Lading form (app/parsers/one_masterbl.py) —
# carrier -> forwarder, distinct from the House BL's forwarder -> cargo-owner
# form (yusen_hbl.py) even though both are issued by Yusen offices. Field set
# overlaps HOUSE_BL heavily on purpose, reusing identical keys for identical
# concepts (shipper/consignee/notify blocks, routing, container numbers).
MASTER_BL: list[dict] = [
    # ---------------------------------------------------------------- Identity
    {"key": "document_type", "label": "Document Type", "group": "Identity", "type": "text",
     "aliases": ["sea waybill", "bill of lading", "master bill of lading"],
     "example": "Sea Waybill"},
    {"key": "bl_number", "label": "B/L No. / Sea Waybill No.", "group": "Identity", "type": "text",
     "aliases": ["sea waybill no", "b/l no", "bill of lading no"],
     "example": "ONEYBKKGS7947600"},
    {"key": "booking_number", "label": "Booking No.", "group": "Identity", "type": "text",
     "aliases": ["booking no"], "example": "BKKGS7947600"},
    {"key": "bl_release_type", "label": "Release Type", "group": "Identity", "type": "text",
     "aliases": ["original non negotiable", "copy non negotiable", "surrendered"],
     "example": "Original Non-Negotiable"},
    {"key": "carrier", "label": "Carrier", "group": "Identity", "type": "text",
     "aliases": ["as carrier"], "example": "Ocean Network Express Pte. Ltd. (ONE), AS CARRIER"},

    # ---------------------------------------------------------------- Parties
    {"key": "shipper", "label": "Shipper", "group": "Parties", "type": "block",
     "aliases": ["shipper/exporter", "shipper"], "example": "YUSEN LOGISTICS (THAILAND) CO.,LTD., ..."},
    {"key": "shipper_name", "label": "Shipper — Name", "group": "Parties", "type": "text",
     "aliases": ["shipper name"], "example": "YUSEN LOGISTICS (THAILAND) CO.,LTD."},
    {"key": "shipper_addr", "label": "Shipper — Address", "group": "Parties", "type": "block",
     "aliases": ["shipper address"], "example": "2525 ONE, TWO FYI CENTER,6TH,7TH F."},
    {"key": "shipper_state", "label": "Shipper — State", "group": "Parties", "type": "text",
     "aliases": ["shipper state"], "example": "THAILAND"},
    {"key": "consignee", "label": "Consignee", "group": "Parties", "type": "block",
     "aliases": ["consignee"], "example": "YUSEN LOGISTICS (INDIA) PVT. LTD., ..."},
    {"key": "consignee_nm", "label": "Consignee — Name", "group": "Parties", "type": "text",
     "aliases": ["consignee name"], "example": "YUSEN LOGISTICS (INDIA) PVT. LTD."},
    {"key": "consignee_addr", "label": "Consignee — Address", "group": "Parties", "type": "block",
     "aliases": ["consignee address"], "example": "UNIT NO.511-513,5TH FLOOR, PALM COURT"},
    {"key": "consignee_state", "label": "Consignee — State", "group": "Parties", "type": "text",
     "aliases": ["consignee state"], "example": "HARYANA"},
    {"key": "notify_party", "label": "Notify Party", "group": "Parties", "type": "block",
     "aliases": ["notify party"], "example": "SAME AS CONSIGNEE"},
    {"key": "notify_name", "label": "Notify — Name", "group": "Parties", "type": "text",
     "aliases": ["notify name"], "example": "SAME AS CONSIGNEE"},
    {"key": "notify_addr", "label": "Notify — Address", "group": "Parties", "type": "block",
     "aliases": ["notify address"], "example": ""},
    {"key": "notify_state", "label": "Notify — State", "group": "Parties", "type": "text",
     "aliases": ["notify state"], "example": ""},

    # ---------------------------------------------------------------- Routing
    {"key": "pre_carriage_by", "label": "Pre-carriage By", "group": "Routing", "type": "text",
     "aliases": ["pre-carriage by"], "example": ""},
    {"key": "place_of_receipt", "label": "Place of Receipt", "group": "Routing", "type": "text",
     "aliases": ["place of receipt"], "example": "LAEM CHABANG, THAILAND"},
    {"key": "vessel_and_voyage", "label": "Vessel / Voyage", "group": "Routing", "type": "text",
     "aliases": ["ocean vessel voyage no", "flag"], "example": "BROOKLYN BRIDGE 0184W"},
    {"key": "port_of_loading", "label": "Port of Loading", "group": "Routing", "type": "text",
     "aliases": ["port of loading"], "example": "LAEM CHABANG, THAILAND"},
    {"key": "final_destination", "label": "Final Destination", "group": "Routing", "type": "text",
     "aliases": ["final destination"], "example": ""},
    {"key": "port_of_discharge", "label": "Port of Discharge", "group": "Routing", "type": "text",
     "aliases": ["port of discharge"], "example": "PIPAVAV, INDIA"},
    {"key": "place_of_delivery", "label": "Place of Delivery", "group": "Routing", "type": "text",
     "aliases": ["place of delivery"], "example": "ICD GARHI HARSARU, INDIA"},
    {"key": "movement_type", "label": "Type of Movement", "group": "Routing", "type": "text",
     "aliases": ["type of movement"], "example": "FCL/FCL CY/CY"},

    # ---------------------------------------------------------------- Cargo
    {"key": "container_and_seal_numbers", "label": "Container & Seal Numbers", "group": "Cargo",
     "type": "list", "aliases": ["cntr nos", "container no"],
     "example": "NYKU0842991, ONEU5873837"},
    {"key": "number_and_kind_of_packages", "label": "Number & Kind of Packages", "group": "Cargo",
     "type": "text", "aliases": ["quantity for customs declaration only"], "example": "38 PALLETS"},
    {"key": "gross_weight", "label": "Gross Weight", "group": "Cargo", "type": "quantity",
     "aliases": ["gross weight"], "example": "5,505.000 KGS"},
    {"key": "measurement_cbm", "label": "Gross Measurement", "group": "Cargo", "type": "quantity",
     "aliases": ["gross measurement"], "example": "66.530 CBM"},
    {"key": "hs_code", "label": "HS Code", "group": "Cargo", "type": "text",
     "aliases": ["hs code", "hs. code"], "example": "85299030"},

    # ------------------------------------------------------------- Commercial
    {"key": "freight_terms", "label": "Freight Terms", "group": "Commercial", "type": "text",
     "aliases": ["freight prepaid", "freight collect"], "example": "FREIGHT COLLECT"},
    {"key": "freight_payable_at", "label": "Freight Payable At", "group": "Commercial",
     "type": "text", "aliases": ["freight charges payable at"], "example": "BANGKOK"},
    {"key": "service_contract_number", "label": "Service Contract No.", "group": "Commercial",
     "type": "text", "aliases": ["service contract no"], "example": "R00000568F8"},
    {"key": "number_of_original_bls", "label": "Number of Original B/Ls", "group": "Commercial",
     "type": "text", "aliases": ["original bill(s) have been signed"], "example": "0"},
    {"key": "shipped_on_board_date", "label": "Shipped On Board Date", "group": "Commercial",
     "type": "date", "aliases": ["date laden on board"], "example": "23 AUG 2026"},
    {"key": "place_and_date_of_issue", "label": "Place & Date of Issue", "group": "Commercial",
     "type": "text", "aliases": ["place of bill(s) issue", "dated"], "example": "BANGKOK, 23 AUG 2026"},
]

# House BL (Import category). Modeled on the Yusen Logistics "for Multimodal
# Transport or Ocean Transport" form (app/parsers/yusen_hbl.py) — field set
# overlaps BILL_OF_LADING heavily on purpose (a House BL *is* a bill of
# lading, just issued by the forwarder/NVOCC rather than the ocean carrier),
# reusing identical keys for identical concepts the same way `hs_code` is
# shared between BILL_OF_LADING and SHIPPING_BILL above.
HOUSE_BL: list[dict] = [
    # ---------------------------------------------------------------- Identity
    {"key": "document_type", "label": "Document Type", "group": "Identity", "type": "text",
     "aliases": ["bill of lading", "house bill of lading",
                 "combined transport shipment", "port to port shipment"],
     "example": "House Bill of Lading"},
    {"key": "bl_number", "label": "B/L Number", "group": "Identity", "type": "text",
     "aliases": ["bill no", "bl no", "bill number", "b/l no"], "example": "BKK1287277"},
    {"key": "carrier", "label": "Carrier", "group": "Identity", "type": "text",
     "aliases": ["carrier", "as carrier"], "example": "YUSEN LOGISTICS (THAILAND) CO.,LTD."},
    {"key": "bl_release_type", "label": "Release Type", "group": "Identity", "type": "text",
     "aliases": ["copy non-negotiable", "original", "surrendered"],
     "example": "Copy Non-Negotiable"},

    # ---------------------------------------------------------------- Parties
    {"key": "shipper", "label": "Shipper", "group": "Parties", "type": "block",
     "aliases": ["shipper"], "example": "DENSO TEN (THAILAND) LIMITED, ..."},
    {"key": "shipper_name", "label": "Shipper — Name", "group": "Parties", "type": "text",
     "aliases": ["shipper name"], "example": "DENSO TEN (THAILAND) LIMITED"},
    {"key": "shipper_addr", "label": "Shipper — Address", "group": "Parties", "type": "block",
     "aliases": ["shipper address"], "example": "253 MOO 11 ROJANA INDUSTRIAL PARK"},
    {"key": "shipper_state", "label": "Shipper — State", "group": "Parties", "type": "text",
     "aliases": ["shipper state"], "example": "THAILAND"},
    {"key": "consignee", "label": "Consignee", "group": "Parties", "type": "block",
     "aliases": ["consignee"], "example": "DENSO TEN UNO MINDA INDIA PRIVATE LIMITED, ..."},
    {"key": "consignee_nm", "label": "Consignee — Name", "group": "Parties", "type": "text",
     "aliases": ["consignee name"], "example": "DENSO TEN UNO MINDA INDIA PRIVATE LIMITED"},
    {"key": "consignee_addr", "label": "Consignee — Address", "group": "Parties", "type": "block",
     "aliases": ["consignee address"], "example": "PLOT NO.383, INDUSTRIAL GROWTH CENTER"},
    {"key": "consignee_state", "label": "Consignee — State", "group": "Parties", "type": "text",
     "aliases": ["consignee state"], "example": "HARYANA"},
    {"key": "notify_party", "label": "Notify Party", "group": "Parties", "type": "block",
     "aliases": ["notify party"], "example": "SAME AS CONSIGNEE"},
    {"key": "notify_name", "label": "Notify — Name", "group": "Parties", "type": "text",
     "aliases": ["notify name"], "example": "SAME AS CONSIGNEE"},
    {"key": "notify_addr", "label": "Notify — Address", "group": "Parties", "type": "block",
     "aliases": ["notify address"], "example": ""},
    {"key": "notify_state", "label": "Notify — State", "group": "Parties", "type": "text",
     "aliases": ["notify state"], "example": ""},
    {"key": "notify_party_2", "label": "Notify Party 2", "group": "Parties", "type": "block",
     "aliases": ["also notify", "notify party 2"], "example": ""},
    {"key": "delivery_agent", "label": "Delivery / Discharge Agent", "group": "Parties",
     "type": "block",
     "aliases": ["for delivery of goods please apply to", "delivery agent"],
     "example": "YUSEN LOGISTICS (INDIA) PVT. LTD., ..."},

    # ---------------------------------------------------------------- Routing
    {"key": "pre_carriage_by", "label": "Pre-carriage By", "group": "Routing", "type": "text",
     "aliases": ["pre-carriage by"], "example": ""},
    {"key": "vessel_and_voyage", "label": "Vessel / Voyage", "group": "Routing",
     "type": "text",
     "aliases": ["ocean vessel", "voy no", "vessel voy no"], "example": "BROOKLYN BRIDGE / 0184W"},
    {"key": "place_of_receipt", "label": "Place of Receipt", "group": "Routing", "type": "text",
     "aliases": ["place of receipt"], "example": "LAEM CHABANG, THAILAND"},
    {"key": "port_of_loading", "label": "Port of Loading", "group": "Routing", "type": "text",
     "aliases": ["port of loading"], "example": "LAEM CHABANG, THAILAND"},
    {"key": "port_of_discharge", "label": "Port of Discharge", "group": "Routing", "type": "text",
     "aliases": ["port of discharge"], "example": "PIPAVAV, INDIA"},
    {"key": "place_of_delivery", "label": "Place of Delivery", "group": "Routing", "type": "text",
     "aliases": ["place of delivery"], "example": "ICD GARHI HARSARU, INDIA"},

    # ---------------------------------------------------------------- Cargo
    {"key": "container_and_seal_numbers", "label": "Container & Seal Numbers", "group": "Cargo",
     "type": "list",
     "aliases": ["container no", "container no. seal no", "seal no"],
     "example": "NYKU0842991, ONEU5873837"},
    {"key": "total_containers", "label": "Total Number of Containers", "group": "Cargo",
     "type": "text",
     "aliases": ["total number of containers or packages"], "example": "TWO CONTAINER(S)"},
    {"key": "marks_and_numbers", "label": "Marks & Numbers", "group": "Cargo", "type": "block",
     "aliases": ["marks & nos", "marks and nos"], "example": ""},
    {"key": "number_and_kind_of_packages", "label": "Number & Kind of Packages", "group": "Cargo",
     "type": "text",
     "aliases": ["no of containers or pkgs", "kind of pkgs"], "example": "38 PLT"},
    {"key": "description_of_goods", "label": "Description of Goods", "group": "Cargo",
     "type": "block", "aliases": ["description of goods"], "example": "2 X 40HC CONTAINER"},
    {"key": "hs_code", "label": "HS Code", "group": "Cargo", "type": "text",
     "aliases": ["hs code", "hs. code"], "example": "85299030"},
    {"key": "gross_weight", "label": "Gross Weight", "group": "Cargo", "type": "quantity",
     "aliases": ["gross weight net", "gross weight (kgs)"], "example": "5,505.000 KGS"},
    {"key": "measurement_cbm", "label": "Measurement (CBM)", "group": "Cargo", "type": "quantity",
     "aliases": ["measurement cbm"], "example": "66.530 CBM"},

    # ------------------------------------------------------------- Commercial
    {"key": "freight_terms", "label": "Freight Terms", "group": "Commercial", "type": "text",
     "aliases": ["freight prepaid", "freight collect"], "example": "FREIGHT COLLECT"},
    {"key": "freight_payable_at", "label": "Freight Payable At", "group": "Commercial",
     "type": "text", "aliases": ["payable at"], "example": "DESTINATION"},
    {"key": "prepaid_at", "label": "Prepaid At", "group": "Commercial", "type": "text",
     "aliases": ["prepaid at"], "example": ""},
    {"key": "exchange_rate", "label": "Ex. Rate", "group": "Commercial", "type": "text",
     "aliases": ["ex rate", "exchange rate"], "example": ""},
    {"key": "total_prepaid_local_currency", "label": "Total Prepaid in Local Currency",
     "group": "Commercial", "type": "text",
     "aliases": ["total prepaid in local currency"], "example": ""},
    {"key": "number_of_original_bls", "label": "Number of Original B/Ls", "group": "Commercial",
     "type": "text", "aliases": ["number of original bills"], "example": "1 (ONE)"},
    {"key": "shipped_on_board_date", "label": "Shipped On Board Date", "group": "Commercial",
     "type": "date", "aliases": ["laden on board vessel", "date"], "example": "23-Aug-26"},
    {"key": "place_and_date_of_issue", "label": "Place & Date of Issue",
     "group": "Commercial", "type": "text",
     "aliases": ["place of bills issued", "dated"], "example": "BANGKOK, 23-Aug-26"},

    # ---------------------------------------------------- Reference documents
    {"key": "invoice_number_and_date", "label": "Invoice No. & Date", "group": "References",
     "type": "text", "aliases": ["invoice no", "inv no"], "example": "2607/098"},
    {"key": "customer_item_number", "label": "Customer Item No.", "group": "References",
     "type": "text", "aliases": ["customer item no"], "example": "39813M55TA1"},
    {"key": "iec_code", "label": "IEC Code", "group": "References", "type": "text",
     "aliases": ["iec no"], "example": "0512052298"},
    {"key": "gstin", "label": "GSTIN (without state code)", "group": "References", "type": "text",
     "aliases": ["gst no", "gstin"], "example": "06AACCF0162H1Z2"},
    {"key": "pan_no", "label": "PAN No.", "group": "References", "type": "text",
     "aliases": ["pan no"], "example": "AACCF0162H"},
]

CATALOGS: dict[str, list[dict]] = {
    "bill_of_lading": BILL_OF_LADING,
    "shipping_bill": SHIPPING_BILL,
    "master_bl": MASTER_BL,
    "house_bl": HOUSE_BL,
}
DOC_TYPES: list[str] = list(CATALOGS)
DEFAULT_DOC_TYPE = "bill_of_lading"

DOC_TYPE_LABELS = {
    "bill_of_lading": "Bill of Lading",
    "shipping_bill": "Shipping Bill",
    "master_bl": "Master Bill of Lading",
    "house_bl": "House Bill of Lading",
}

# Back-compat aliases (BL catalog).
FIELD_CATALOG = BILL_OF_LADING
FIELD_KEYS: list[str] = [f["key"] for f in BILL_OF_LADING]

_BY_KEY: dict[str, dict] = {}
for _dt, _specs in CATALOGS.items():
    for _f in _specs:
        _BY_KEY.setdefault(_f["key"], {**_f, "doc_type": _dt})


def catalog(doc_type: str = DEFAULT_DOC_TYPE) -> list[dict]:
    return CATALOGS[doc_type]


def field_keys(doc_type: str = DEFAULT_DOC_TYPE) -> list[str]:
    return [f["key"] for f in CATALOGS[doc_type]]


def get_field(key: str) -> dict:
    return _BY_KEY[key]


def groups(doc_type: str = DEFAULT_DOC_TYPE) -> list[str]:
    seen: list[str] = []
    for f in CATALOGS[doc_type]:
        if f["group"] not in seen:
            seen.append(f["group"])
    return seen
