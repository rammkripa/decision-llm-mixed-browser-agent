export const examples = {
  get flights() {
    const departure = new Date();
    departure.setDate(departure.getDate() + 60);
    const date = [departure.getFullYear(), String(departure.getMonth() + 1).padStart(2, '0'), String(departure.getDate()).padStart(2, '0')].join('-');
    return {url:'https://www.google.com/travel/flights?hl=en',goal:`Find one-way flights from Zurich to London on ${date}, for one adult in economy. Report the top three available options with airline, departure and arrival times, and prices.`};
  },
  books: {url:'https://books.toscrape.com',goal:'Find the product page for A Light in the Attic. Report its title, price, and UPC. Check whether an ISBN is listed; if absent, say that this page does not provide one.'},
  webb: {url:'https://en.wikipedia.org/wiki/Main_Page',goal:'James Webb Space Telescope: Report its launch date, the launch vehicle, and why it operates near the Sun-Earth L2 point. Cite supporting sources.'},
  python: {url:'https://www.google.com',goal:"Find Python's official documentation explaining list.sort() and sorted(). Explain which modifies the original list and which returns a new list, with the documentation URL."}
};
