<!--
Business knowledge the model can't see in the schema. This is the biggest lever on accuracy.
Separate topics with a line containing only ---  (each topic is stored and retrieved separately).
Status values below are the ones seen in the data so far; add new ones as they appear.
-->

# What this database is
A fleet / transport management system for a transporter. Trips carry goods (freight) or
passengers for customers, using the company's vehicles (tvehicle) and drivers (tdriver).
Trips are billed through invoices (tripinvoice, with lines in tripinvoiceitem).
Running costs are tracked in fuel, maintenance (+ maintenanceparts) and tyremaster.
All money amounts are in Indian Rupees (INR). Distances are in kilometres, fuel quantity in litres.

---

# How the tables join
- trip.customer = customer.customerid
- trip.driver = tdriver.tdriverid
- trip.vehicle = tvehicle.tvehicleid
- tripinvoice.tripid = trip.tripid (a trip can have more than one invoice)
- tripinvoice.customer = customer.customerid, tripinvoice.tdriverid = tdriver.tdriverid, tripinvoice.tvehicleid = tvehicle.tvehicleid
- tripinvoiceitem.invoiceid = tripinvoice.invoiceid
- tripwaypoints.tripid = trip.tripid (stops in order of sequenceno)
- fuel.vehicle = tvehicle.tvehicleid, fuel.driver = tdriver.tdriverid
- maintenance.vehicle = tvehicle.tvehicleid; maintenanceparts.maintenanceid = maintenance.maintenanceid
- tyremaster.vehicle = tvehicle.tvehicleid
- customeraddress.customerid = customer.customerid
- tdriverdocuments.tdriverid = tdriver.tdriverid; tvehicledocuments.tvehicleid = tvehicle.tvehicleid
- companyaddress / companybankdetails .companyprofileid = companyprofile.companyprofileid
- userid columns point to users.userid = the login that created the record, not a driver or customer.
Important traps:
- tvehicle.driver is a driver NAME stored as text, not an id. To link vehicles and drivers use trip.driver and trip.vehicle.
- trip.invoice_no is an internal reference code, NOT tripinvoice.invoiceid. Join invoices with tripinvoice.tripid = trip.tripid.

---

# Cancelled and inactive records
Most tables have cancel and active flags stored as BIT(1).
Always exclude cancelled records: add cancel = 0 for every table that has a cancel column, unless the question asks about cancelled records.
Write the conditions as cancel = 0 and active = 1 (never cancel = 'false').
Exception: tvehicle.active is text, with value 'ACTIVE' for active vehicles.
Never use SELECT *; always list the columns needed.

---

# Dates
Use the real DATE columns for business dates:
trip.startdate / trip.enddate (trip.tripstarttime / trip.tripendtime are the actual start and end timestamps),
tripinvoice.issuedate / duedate / paymentdate, fuel.fueldate, maintenance.scheduleddate / completeddate,
tyremaster.purchasedate, tdriver.joineddate.
createdon and modifiedon are TEXT in the format 'DD-MM-YYYY hh:mm:ss AM' (example '19-09-2026 03:29:13 PM').
Only use them when no business date exists, and convert first: STR_TO_DATE(createdon, '%d-%m-%Y %h:%i:%s %p').
Date ranges always need BOTH a start and an end:
- "this month": d >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
- "last month" / "previous month": d >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%Y-%m-01') AND d < DATE_FORMAT(CURDATE(), '%Y-%m-01')
- "this year": d >= MAKEDATE(YEAR(CURDATE()), 1)
- "last N days": d >= CURDATE() - INTERVAL N DAY
where d is the business date column (trip.startdate, fuel.fueldate, tripinvoice.issuedate...).

---

# Trip revenue, cost and profit
Each trip stores its own figures:
- trip.revenue = amount charged to the customer for the trip
- trip.fuelcost, trip.tollcharges, trip.otherexpenses = cost components
- trip.tripcost = total cost of the trip
- trip.profit = profit of the trip; use this stored column for profit questions
Revenue, cost or profit by customer, vehicle, driver, route or month = SUM of these trip columns, grouped as asked.
Trip status values: 'COMPLETED'. Trip types (triptype): 'freight', 'passenger'.
A route is source -> destination. trip.distance is in km.
Cargo details are on the trip row itself: goodstype, goodsweight, goodsvalue. Don't join invoices to answer questions about trips.

---

# Invoices, billing and outstanding payments
tripinvoice is the bill sent to a customer. totalamount = subtotal - discount + taxamount (taxrate is a percent, GST).
GST / tax billed = SUM(tripinvoice.taxamount) over all non-cancelled invoices, whatever their status.
Only filter on status when the question asks about paid, draft, etc. invoices.
amountpaid = amount received so far; balancedue = amount still to be collected.
Outstanding / receivables / pending payment = SUM(tripinvoice.balancedue) where balancedue > 0 and cancel = 0.
Invoiced amount = SUM(tripinvoice.totalamount). Collected = SUM(tripinvoice.amountpaid).
Overdue invoices: balancedue > 0 AND duedate < CURDATE().
Invoice status values (lower case): 'draft', 'paid'. paymentmethod values: 'bank_transfer'.
tripinvoiceitem has the invoice lines: amount = quantity * rate. Don't SUM tripinvoice.totalamount after joining to tripinvoiceitem, because the invoice total repeats once per line.
For billed revenue use tripinvoice; for operational revenue use trip.revenue.

---

# Fuel
One row per fuel fill-up. fuel.quantity = litres, fuel.cost = total amount paid for that fill-up (not price per litre).
Price per litre = cost / quantity. Total fuel spend = SUM(fuel.cost).
odometerreading - previousodometer = km driven since the previous fill-up; mileage (km per litre) = (odometerreading - previousodometer) / quantity.
fueltype values (lower case): 'diesel', 'petrol'.

---

# Maintenance and tyres
maintenance is one service job for a vehicle. estimatedcost = planned cost; totalcost = actual cost (0 until done).
Maintenance spend = SUM(maintenance.totalcost). maintenanceparts lists the parts used (cost, quantity, name).
maintenance.status values (lower case): 'pending', 'completed'. type: 'preventive'. priority: 'medium'.
Upcoming service: maintenance.status = 'pending' with scheduleddate, or tvehicle.nextservice.
tyremaster is one row per tyre fitted to a vehicle: brand, size, position ('Front Left', 'Front Right'...),
purchasecost, treaddepth, pressure vs recommendedpressure. status values: 'active', 'repair'.

---

# Vehicles, drivers and expiring documents
tvehicle: vehiclenumber is the registration number people use to refer to a vehicle.
type values: 'OPEN_TRUCK', 'TANKER', 'TRAILER', 'TIPPER'.
Compliance expiry dates on tvehicle: insuranceexpiry, fitnessexpiry (FC), pucexpiry (pollution certificate).
Driver licence expiry: tdriver.licenseexpiry. "Expiring soon" = between CURDATE() and CURDATE() + INTERVAL 30 DAY.
tdriver.status values: 'Active'. tdriver.performance is text like '4.5/5'. tdriver.salary and experience are text.
Uploaded documents: tdriverdocuments.documenttype in ('DL', 'AADHAR', 'PHOTO'); tvehicledocuments.documenttype in ('RC', 'INSURANCE', 'FC').

---

# Customers and the company
customer.customername is the customer's name, customercode its short code. salesperson = account owner.
City and state are in customeraddress (join on customerid).
companyprofile, companyaddress and companybankdetails describe the transporter itself (the company using this system).
users are the system logins (usertype 'ADMIN' or 'USER'), not drivers or customers.
