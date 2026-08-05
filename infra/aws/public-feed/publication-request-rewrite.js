function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (
    uri.indexOf("/publications/") === 0 &&
    uri.charAt(uri.length - 1) !== "/" &&
    uri.lastIndexOf(".") <= uri.lastIndexOf("/")
  ) {
    request.uri = uri + ".html";
  }

  return request;
}
