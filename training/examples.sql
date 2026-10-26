-- Verified question/SQL pairs. 20-50 good ones covering your common questions help accuracy a lot.
-- Format: a "-- Q:" line with the question, then the SQL. train.py checks each one with EXPLAIN
-- against the live database and skips any that are invalid or touch non-business tables.

-- Q: What is the total revenue, cost and profit from trips this month?
SELECT SUM(revenue) AS revenue, SUM(tripcost) AS cost, SUM(profit) AS profit
FROM trip
WHERE cancel = 0
  AND startdate >= DATE_FORMAT(CURDATE(), '%Y-%m-01');

-- Q: Show monthly trip revenue and profit
SELECT DATE_FORMAT(startdate, '%Y-%m') AS month,
       COUNT(*) AS trips, SUM(revenue) AS revenue, SUM(profit) AS profit
FROM trip
WHERE cancel = 0
GROUP BY DATE_FORMAT(startdate, '%Y-%m')
ORDER BY month;

-- Q: Which customers bring the most revenue?
SELECT c.customername, COUNT(t.tripid) AS trips, SUM(t.revenue) AS revenue, SUM(t.profit) AS profit
FROM trip t
JOIN customer c ON c.customerid = t.customer
WHERE t.cancel = 0
GROUP BY c.customerid, c.customername
ORDER BY revenue DESC
LIMIT 10;

-- Q: Profit by vehicle
SELECT v.vehiclenumber, v.type, COUNT(t.tripid) AS trips, SUM(t.distance) AS km,
       SUM(t.revenue) AS revenue, SUM(t.tripcost) AS cost, SUM(t.profit) AS profit
FROM trip t
JOIN tvehicle v ON v.tvehicleid = t.vehicle
WHERE t.cancel = 0
GROUP BY v.tvehicleid, v.vehiclenumber, v.type
ORDER BY profit DESC;

-- Q: How many trips and kilometres has each driver done?
SELECT d.name AS driver, COUNT(t.tripid) AS trips, SUM(t.distance) AS km, SUM(t.revenue) AS revenue
FROM trip t
JOIN tdriver d ON d.tdriverid = t.driver
WHERE t.cancel = 0
GROUP BY d.tdriverid, d.name
ORDER BY trips DESC;

-- Q: What are the most frequent routes?
SELECT source, destination, COUNT(*) AS trips, AVG(distance) AS avg_km, SUM(revenue) AS revenue
FROM trip
WHERE cancel = 0
GROUP BY source, destination
ORDER BY trips DESC
LIMIT 10;

-- Q: How much payment is outstanding from each customer?
SELECT c.customername, COUNT(i.invoiceid) AS open_invoices,
       SUM(i.totalamount) AS invoiced, SUM(i.amountpaid) AS paid, SUM(i.balancedue) AS outstanding
FROM tripinvoice i
JOIN customer c ON c.customerid = i.customer
WHERE i.cancel = 0 AND i.balancedue > 0
GROUP BY c.customerid, c.customername
ORDER BY outstanding DESC;

-- Q: List overdue invoices
SELECT i.invoiceid, c.customername, i.issuedate, i.duedate,
       DATEDIFF(CURDATE(), i.duedate) AS days_overdue, i.totalamount, i.balancedue, i.status
FROM tripinvoice i
JOIN customer c ON c.customerid = i.customer
WHERE i.cancel = 0 AND i.balancedue > 0 AND i.duedate < CURDATE()
ORDER BY days_overdue DESC;

-- Q: How much GST have we billed, collected and still to collect?
SELECT SUM(subtotal) AS taxable_value, SUM(taxamount) AS gst_billed,
       SUM(totalamount) AS invoiced, SUM(amountpaid) AS collected, SUM(balancedue) AS outstanding
FROM tripinvoice
WHERE cancel = 0;

-- Q: Show freight trips with their cargo details
SELECT t.tripid, t.startdate, c.customername, t.source, t.destination,
       t.goodstype, t.goodsweight, t.goodsvalue, t.revenue
FROM trip t
LEFT JOIN customer c ON c.customerid = t.customer
WHERE t.cancel = 0 AND t.triptype = 'freight'
ORDER BY t.startdate DESC;

-- Q: Show invoices with their trip route and customer
SELECT i.invoiceid, i.issuedate, c.customername, t.source, t.destination, t.startdate,
       i.subtotal, i.discount, i.taxamount, i.totalamount, i.balancedue, i.status
FROM tripinvoice i
JOIN trip t ON t.tripid = i.tripid
JOIN customer c ON c.customerid = i.customer
WHERE i.cancel = 0
ORDER BY i.issuedate DESC;

-- Q: Total fuel cost and litres by vehicle
SELECT v.vehiclenumber, COUNT(*) AS fill_ups, SUM(f.quantity) AS litres, SUM(f.cost) AS fuel_cost,
       ROUND(SUM(f.cost) / SUM(f.quantity), 2) AS avg_price_per_litre
FROM fuel f
JOIN tvehicle v ON v.tvehicleid = f.vehicle
WHERE f.cancel = 0
GROUP BY v.tvehicleid, v.vehiclenumber
ORDER BY fuel_cost DESC;

-- Q: Which vehicle used the most fuel last month?
SELECT v.vehiclenumber, SUM(f.quantity) AS litres, SUM(f.cost) AS fuel_cost
FROM fuel f
JOIN tvehicle v ON v.tvehicleid = f.vehicle
WHERE f.cancel = 0
  AND f.fueldate >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%Y-%m-01')
  AND f.fueldate <  DATE_FORMAT(CURDATE(), '%Y-%m-01')
GROUP BY v.tvehicleid, v.vehiclenumber
ORDER BY litres DESC
LIMIT 1;

-- Q: What is the mileage (km per litre) of each vehicle?
SELECT v.vehiclenumber,
       ROUND(SUM(f.odometerreading - f.previousodometer) / SUM(f.quantity), 2) AS km_per_litre
FROM fuel f
JOIN tvehicle v ON v.tvehicleid = f.vehicle
WHERE f.cancel = 0 AND f.previousodometer IS NOT NULL AND f.quantity > 0
GROUP BY v.tvehicleid, v.vehiclenumber
ORDER BY km_per_litre DESC;

-- Q: Maintenance cost by vehicle
SELECT v.vehiclenumber, COUNT(m.maintenanceid) AS jobs,
       SUM(m.estimatedcost) AS estimated, SUM(m.totalcost) AS actual
FROM maintenance m
JOIN tvehicle v ON v.tvehicleid = m.vehicle
WHERE m.cancel = 0
GROUP BY v.tvehicleid, v.vehiclenumber
ORDER BY actual DESC;

-- Q: Which maintenance jobs are pending?
SELECT v.vehiclenumber, m.title, m.type, m.priority, m.scheduleddate, m.servicecenter, m.estimatedcost
FROM maintenance m
JOIN tvehicle v ON v.tvehicleid = m.vehicle
WHERE m.cancel = 0 AND m.status = 'pending'
ORDER BY m.scheduleddate;

-- Q: Which vehicles have insurance, fitness or PUC expiring in the next 30 days?
SELECT vehiclenumber, insuranceexpiry, fitnessexpiry, pucexpiry
FROM tvehicle
WHERE cancel = 0
  AND (insuranceexpiry BETWEEN CURDATE() AND CURDATE() + INTERVAL 30 DAY
    OR fitnessexpiry   BETWEEN CURDATE() AND CURDATE() + INTERVAL 30 DAY
    OR pucexpiry       BETWEEN CURDATE() AND CURDATE() + INTERVAL 30 DAY)
ORDER BY LEAST(IFNULL(insuranceexpiry, '9999-12-31'), IFNULL(fitnessexpiry, '9999-12-31'), IFNULL(pucexpiry, '9999-12-31'));

-- Q: Which drivers' licences expire in the next 30 days?
SELECT name, phone, licensenumber, licenseexpiry
FROM tdriver
WHERE cancel = 0 AND licenseexpiry BETWEEN CURDATE() AND CURDATE() + INTERVAL 30 DAY
ORDER BY licenseexpiry;

-- Q: Which tyres are under-inflated?
SELECT v.vehiclenumber, ty.position, ty.brand, ty.serialnumber, ty.pressure, ty.recommendedpressure, ty.status
FROM tyremaster ty
JOIN tvehicle v ON v.tvehicleid = ty.vehicle
WHERE ty.cancel = 0 AND ty.pressure < ty.recommendedpressure
ORDER BY (ty.recommendedpressure - ty.pressure) DESC;

-- Q: Total operating cost per vehicle (fuel + maintenance + tyres)
SELECT v.vehiclenumber,
       IFNULL(f.fuel_cost, 0) AS fuel_cost,
       IFNULL(m.maintenance_cost, 0) AS maintenance_cost,
       IFNULL(ty.tyre_cost, 0) AS tyre_cost,
       IFNULL(f.fuel_cost, 0) + IFNULL(m.maintenance_cost, 0) + IFNULL(ty.tyre_cost, 0) AS total_cost
FROM tvehicle v
LEFT JOIN (SELECT vehicle, SUM(cost) AS fuel_cost FROM fuel WHERE cancel = 0 GROUP BY vehicle) f ON f.vehicle = v.tvehicleid
LEFT JOIN (SELECT vehicle, SUM(totalcost) AS maintenance_cost FROM maintenance WHERE cancel = 0 GROUP BY vehicle) m ON m.vehicle = v.tvehicleid
LEFT JOIN (SELECT vehicle, SUM(purchasecost) AS tyre_cost FROM tyremaster WHERE cancel = 0 GROUP BY vehicle) ty ON ty.vehicle = v.tvehicleid
WHERE v.cancel = 0
ORDER BY total_cost DESC;

-- Q: List customers with their city and contact person
SELECT c.customercode, c.customername, a.city, a.state, c.pocname, c.pocnumber, c.salesperson
FROM customer c
LEFT JOIN customeraddress a ON a.customerid = c.customerid
WHERE c.cancel = 0
ORDER BY c.customername;
