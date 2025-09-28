	Problem:
	The client uses a government website to sell goods in procurement procedures using budget funds and must sign a large number of 
contracts in their personal account using an electronic key. There are no more than three working days to sign the contract. If the 
contract is not signed within three working days, the client will be suspended from budget-funded procurement for three years for 
evading the signing of the contract. The main problem is that, in addition to notifications about contracts, the user's personal 
account receives a large number of other system messages due to the peculiarities of the website, which spam the section, cannot be 
sorted, and make it possible to miss a message related to the signing of a contract. Approximately 200-300 messages are received.
	In addition, in order for the contract to be signed, depending on its amount, it is necessary to: 
1) Declare compliance with legal requirements 
and upload documents; 
2) Wait for notification that the client is eligible and the application has been approved; 
3) Make the payment;
4) Wait for the payment to be confirmed;
5) Review the contract; 
6) If there are errors in the contract, write an objection requesting that they be corrected; 
7) Wait for a new version of the contract and sign it, either sign it without writing an objection, or write a repeat objection and sign 
it after all inaccuracies have been corrected. (There are also agreements ready for signing immediately after posting.)
	To simplify the work, there is a page on the website where contracts are collected and there is a filter, but it does not filter by the 
specified data, but only allows you to view all contracts that are posted for signing, from which it is impossible to conclude what stage 
the contract is currently at without going to the contract card. 
Dozens of contracts arrive on the platform every day, and since many are not signed during the day, they can accumulate, and they need to 
be signed as quickly as possible so as not to disrupt the logistics of deliveries. One person is responsible for signing contracts, which 
creates risks, but due to bureaucratic peculiarities, it is not possible to increase the number of responsible persons.
	Additionally, there are restrictions on access to the site:
1) Access is only available from Belarus and Russia, with control exercised via IP;
2) Standard tracking of the number of requests and blocking of IP addresses with excessive activity;
3) Access via login and password.

	Solution:
	The developed solution is a crawler with a simple UI and sound accompaniment.
1) The crawler in the UI accepts a list of proxies in a specific format and then, when creating a session, randomly selects from the list to log in to the site.
The list of proxies entered once is saved in the config.json file and does not need to be re-entered when restarting the crawler.
2) The code implements website login if the website redirects to a login page. During repeated visits, the program automatically checks whether re-login is necessary 
and performs it if the user's data is saved. User data is entered via the UI, and a checkbox is implemented to save user data in the config.json file.
3) For continuous monitoring of new contracts and/or changes in their status, crawling runs cyclically, i.e., the number of minutes after which the crawl should be 
repeated is entered in the corresponding UI window. To track this parameter, the interface provides a countdown timer until the next crawl.
4) In addition to monitoring at specified intervals, there is also the option of performing a one-time check. The selection is made using the corresponding UI 
buttons: start monitoring, stop monitoring, one-time check.
5) To prevent blocking by the site, in addition to replacing the IP address when reconnecting (if there is a proxy list), a system of delays has been implemented that 
simulates human behavior on the site, and tasks in loops are divided into chunks, between which some of the delays are set
6) To speed up the process, all code is implemented in asynchronous style, and caching is also performed in the cache.json file
7) User notifications about the appearance of new contracts with a particular status, as well as about changes in the status of existing contracts in the cache, are 
carried out by means of a pop-up window that appears on top of all other windows and is accompanied by an audible signal, which varies depending on the content of the 
pop-up window
8) Popup has three distinct sections containing links directly to the contract page: 1) Ready for signing — all actions have been completed, or no action is required; 2) Requires application - you need to go from the pop-up to the contract card and submit an application for compliance with legal requirements, attaching the necessary documents and signing the application with an electronic key; 3) Pending - the application has not yet been reviewed by the customer and/or payment has not yet been made.
10) When transitioning from one status to another, the user also receives an audio notification along with a pop-up notification.

	This crawler solves the problem of controlling a large number of messages by selecting and aggregating only those that are necessary in the context of the task and displaying 
a noticeable message to the user. This prevents the client from being included in the list of companies not allowed to participate in public procurement, as well as maintaining 
the speed of document flow and preventing logistical delays, which prevents sanctions due to delays, maintains the company's image, and increases the turnover rate.
