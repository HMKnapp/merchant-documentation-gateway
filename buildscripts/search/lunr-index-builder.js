// Generates lunr compatible search index
// from HTMl generated by asciidoctor
// Author Herbert Knapp
// For Wirecard CEE

const cheerio = require('cheerio');
var fs = require('fs');
var lunr = require('lunr');

try {
    var htmlFile = fs.readFileSync('index.html');
} catch (err) {
    console.log("\nfile read error\n");
    process.exit(1);
}

const $ = cheerio.load( htmlFile );

var listSelector = "#content .sect1, #content .sect2, #content .sect3";
var idx = lunr(function() {
  // define searchable fields
  this.ref("id");
  this.field("title");
  this.field("body");

  this.k1(1.3)
  this.b(0)

  function htmlElementsToJSON(listSelector, unmarshalFunction) {
    // add the list elements to lunr
    var qs = $(listSelector);
    var entries = [];
    for (var i = 0; i < qs.length; i++) {
      var $q = $(qs[i]);
      entries.push(unmarshalFunction($q));
    }
    return entries;
  }

  var documents = htmlElementsToJSON(listSelector, function($element) {
    var ref = $element.find("h2, h3, h4").attr('id');
    var title = $element.find("h2, h3, h4").text();
    var body = $element.find("p").text();
    return { id: ref, title: title, body: body };
  });

  // adding all entires to lunr
  documents.forEach(function(doc) {
    this.add(doc);
  }, this);
  //console.log(documents);
});

fs.writeFileSync('searchIndex.json', JSON.stringify(idx));
