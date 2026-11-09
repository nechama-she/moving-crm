// The time-of-day greeting at the top of the Leads page.
export const greeting = (date = new Date()) => (date.getHours() < 12 ? "Good morning" : date.getHours() < 18 ? "Good afternoon" : "Good evening");
