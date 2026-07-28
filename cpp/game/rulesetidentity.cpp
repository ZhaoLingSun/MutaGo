#include "../game/rulesetidentity.h"

#include <limits>
#include <regex>

#include "../core/sha2.h"

using nlohmann::json;
using namespace std;

const string RulesetIdentity::PUBLIC_RULESET_ID = "mutago.collapse-go";
const string RulesetIdentity::PUBLIC_SEMANTIC_VERSION = "0.1.0-draft";
const string RulesetIdentity::PUBLIC_DESCRIPTOR_SHA256 = "a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899";
const string RulesetIdentity::DESCRIPTOR_SCHEMA_ID = "ruleset-descriptor-v1.schema.json";
const string RulesetIdentity::DESCRIPTOR_SCHEMA_SHA256 = "80ff4a3f089a647b92b5f3dc5c9ab8820351730e195b5cd5a117661532a8e5dd";
const string RulesetIdentity::CANONICALIZATION_PROFILE = "rfc8785-jcs-ascii-safe-integer-v1";

RulesetIdentityError::RulesetIdentityError(const string& errorCode, const string& errorMessage)
  : StringError(errorMessage), code(errorCode)
{}

const string& RulesetIdentityError::getCode() const {
  return code;
}

namespace {

constexpr size_t MAX_JSON_DEPTH = 1024;

[[noreturn]] void failIdentity(const string& code, const string& message) {
  throw RulesetIdentityError(code,message);
}

void validateUtf8(const string& raw) {
  size_t pos = 0;
  while(pos < raw.size()) {
    uint32_t first = static_cast<unsigned char>(raw[pos]);
    if(first <= 0x7F) {
      pos += 1;
      continue;
    }

    size_t length;
    uint32_t codePoint;
    uint32_t minimum;
    if(first >= 0xC2 && first <= 0xDF) {
      length = 2;
      codePoint = first & 0x1F;
      minimum = 0x80;
    }
    else if(first >= 0xE0 && first <= 0xEF) {
      length = 3;
      codePoint = first & 0x0F;
      minimum = 0x800;
    }
    else if(first >= 0xF0 && first <= 0xF4) {
      length = 4;
      codePoint = first & 0x07;
      minimum = 0x10000;
    }
    else
      failIdentity("invalid-utf8","Input is not valid UTF-8");

    if(length > raw.size() - pos)
      failIdentity("invalid-utf8","Input ends inside a UTF-8 sequence");
    for(size_t i = 1; i < length; i++) {
      uint32_t next = static_cast<unsigned char>(raw[pos+i]);
      if((next & 0xC0) != 0x80)
        failIdentity("invalid-utf8","Input contains an invalid UTF-8 continuation byte");
      codePoint = (codePoint << 6) | (next & 0x3F);
    }
    if(codePoint < minimum || codePoint > 0x10FFFF || (codePoint >= 0xD800 && codePoint <= 0xDFFF))
      failIdentity("invalid-utf8","Input contains an invalid UTF-8 code point");
    pos += length;
  }
}

struct RestrictedParsedValue {
  json value;
  string profileErrorCode;
  string profileErrorMessage;

  explicit RestrictedParsedValue(json parsedValue)
    : value(std::move(parsedValue)), profileErrorCode(), profileErrorMessage()
  {}

  void copyProfileErrorFrom(const RestrictedParsedValue& other) {
    if(profileErrorCode.empty() && !other.profileErrorCode.empty()) {
      profileErrorCode = other.profileErrorCode;
      profileErrorMessage = other.profileErrorMessage;
    }
  }
};

class RestrictedJsonParser {
public:
  explicit RestrictedJsonParser(const string& rawInput)
    : input(rawInput), pos(0)
  {}

  json parse() {
    skipWhitespace();
    if(pos >= input.size())
      fail("invalid-json","JSON input is empty");
    RestrictedParsedValue parsed = parseValue(0);
    skipWhitespace();
    if(pos != input.size())
      fail("invalid-json","Unexpected trailing data after the JSON value");
    if(!parsed.profileErrorCode.empty())
      fail(parsed.profileErrorCode,parsed.profileErrorMessage);
    return std::move(parsed.value);
  }

private:
  const string& input;
  size_t pos;

  [[noreturn]] void fail(const string& code, const string& message) const {
    failIdentity(code,message + " at byte " + Global::sizeToString(pos));
  }

  void skipWhitespace() {
    while(pos < input.size()) {
      char c = input[pos];
      if(c != ' ' && c != '\t' && c != '\n' && c != '\r')
        break;
      pos += 1;
    }
  }

  bool startsWith(const char* literal) const {
    size_t i = 0;
    while(literal[i] != '\0') {
      if(pos+i >= input.size() || input[pos+i] != literal[i])
        return false;
      i += 1;
    }
    return true;
  }

  void consumeLiteral(const char* literal) {
    size_t i = 0;
    while(literal[i] != '\0') {
      if(pos >= input.size() || input[pos] != literal[i])
        fail("invalid-json","Invalid JSON literal");
      pos += 1;
      i += 1;
    }
  }

  static bool containsNonAscii(const string& value) {
    for(unsigned char byte: value) {
      if(byte > 0x7F)
        return true;
    }
    return false;
  }

  RestrictedParsedValue parseValue(size_t depth) {
    if(depth > MAX_JSON_DEPTH)
      fail("resource-limit","JSON nesting exceeds the supported depth");
    skipWhitespace();
    if(pos >= input.size())
      fail("invalid-json","Unexpected end of JSON input");

    char c = input[pos];
    if(c == '{')
      return parseObject(depth+1);
    if(c == '[')
      return parseArray(depth+1);
    if(c == '"') {
      string text = parseString(false);
      RestrictedParsedValue parsed{json(text)};
      if(containsNonAscii(text)) {
        parsed.profileErrorCode = "non-ascii-string";
        parsed.profileErrorMessage = "Non-ASCII JSON string";
      }
      return parsed;
    }
    if(c == 't') {
      consumeLiteral("true");
      return RestrictedParsedValue(json(true));
    }
    if(c == 'f') {
      consumeLiteral("false");
      return RestrictedParsedValue(json(false));
    }
    if(c == 'n') {
      if(startsWith("null")) {
        consumeLiteral("null");
        return RestrictedParsedValue(json(nullptr));
      }
      fail("invalid-json","Invalid JSON literal");
    }
    if(startsWith("NaN") || startsWith("Infinity") || startsWith("-Infinity"))
      fail("invalid-json-number","Non-JSON numeric constants are forbidden");
    if(c == '-' || (c >= '0' && c <= '9'))
      return RestrictedParsedValue(parseInteger());
    fail("invalid-json","Unexpected token while parsing JSON");
  }

  RestrictedParsedValue parseObject(size_t depth) {
    if(depth > MAX_JSON_DEPTH)
      fail("resource-limit","JSON nesting exceeds the supported depth");
    pos += 1;
    skipWhitespace();
    json value = json::object();
    if(pos < input.size() && input[pos] == '}') {
      pos += 1;
      return RestrictedParsedValue(std::move(value));
    }

    bool foundDuplicate = false;
    string firstDuplicateKey;
    bool foundNonAsciiKey = false;
    string nonAsciiKey;
    RestrictedParsedValue firstChildWithProfileError{json(nullptr)};
    while(true) {
      skipWhitespace();
      if(pos >= input.size() || input[pos] != '"')
        fail("invalid-json","JSON object key must be a string");
      string key = parseString(true);
      if(containsNonAscii(key)) {
        foundNonAsciiKey = true;
        nonAsciiKey = key;
      }
      bool duplicate = value.find(key) != value.end();
      skipWhitespace();
      if(pos >= input.size() || input[pos] != ':')
        fail("invalid-json","JSON object key is not followed by ':'");
      pos += 1;
      RestrictedParsedValue child = parseValue(depth);
      firstChildWithProfileError.copyProfileErrorFrom(child);
      if(!duplicate)
        value[key] = std::move(child.value);
      else if(!foundDuplicate) {
        foundDuplicate = true;
        firstDuplicateKey = key;
      }
      skipWhitespace();
      if(pos >= input.size())
        fail("invalid-json","Unexpected end of JSON object");
      if(input[pos] == '}') {
        pos += 1;
        if(foundDuplicate)
          fail("duplicate-key","Duplicate JSON object key: " + firstDuplicateKey);
        RestrictedParsedValue parsed{std::move(value)};
        if(foundNonAsciiKey) {
          parsed.profileErrorCode = "non-ascii-key";
          parsed.profileErrorMessage = "Non-ASCII JSON object key: " + nonAsciiKey;
        }
        else
          parsed.copyProfileErrorFrom(firstChildWithProfileError);
        return parsed;
      }
      if(input[pos] != ',')
        fail("invalid-json","JSON object entries must be separated by ','");
      pos += 1;
    }
  }

  RestrictedParsedValue parseArray(size_t depth) {
    if(depth > MAX_JSON_DEPTH)
      fail("resource-limit","JSON nesting exceeds the supported depth");
    pos += 1;
    skipWhitespace();
    json value = json::array();
    if(pos < input.size() && input[pos] == ']') {
      pos += 1;
      return RestrictedParsedValue(std::move(value));
    }

    RestrictedParsedValue firstChildWithProfileError{json(nullptr)};
    while(true) {
      RestrictedParsedValue child = parseValue(depth);
      firstChildWithProfileError.copyProfileErrorFrom(child);
      value.push_back(std::move(child.value));
      skipWhitespace();
      if(pos >= input.size())
        fail("invalid-json","Unexpected end of JSON array");
      if(input[pos] == ']') {
        pos += 1;
        RestrictedParsedValue parsed{std::move(value)};
        parsed.copyProfileErrorFrom(firstChildWithProfileError);
        return parsed;
      }
      if(input[pos] != ',')
        fail("invalid-json","JSON array entries must be separated by ','");
      pos += 1;
    }
  }

  static int hexDigitValue(char c) {
    if(c >= '0' && c <= '9')
      return c-'0';
    if(c >= 'a' && c <= 'f')
      return c-'a'+10;
    if(c >= 'A' && c <= 'F')
      return c-'A'+10;
    return -1;
  }

  bool parseHexCodeUnitAt(size_t start, uint32_t& codeUnit) const {
    if(start > input.size() || input.size() - start < 4)
      return false;
    codeUnit = 0;
    for(int i = 0; i < 4; i++) {
      int digit = hexDigitValue(input[start+i]);
      if(digit < 0)
        return false;
      codeUnit = (codeUnit << 4) | static_cast<uint32_t>(digit);
    }
    return true;
  }

  static void appendUtf8(string& result, uint32_t codePoint) {
    if(codePoint <= 0x7F)
      result.push_back(static_cast<char>(codePoint));
    else if(codePoint <= 0x7FF) {
      result.push_back(static_cast<char>(0xC0 | (codePoint >> 6)));
      result.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    }
    else if(codePoint <= 0xFFFF) {
      result.push_back(static_cast<char>(0xE0 | (codePoint >> 12)));
      result.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
      result.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    }
    else {
      result.push_back(static_cast<char>(0xF0 | (codePoint >> 18)));
      result.push_back(static_cast<char>(0x80 | ((codePoint >> 12) & 0x3F)));
      result.push_back(static_cast<char>(0x80 | ((codePoint >> 6) & 0x3F)));
      result.push_back(static_cast<char>(0x80 | (codePoint & 0x3F)));
    }
  }

  string parseString(bool isKey) {
    (void)isKey;
    pos += 1;
    string result;
    while(pos < input.size()) {
      unsigned char byte = static_cast<unsigned char>(input[pos]);
      pos += 1;
      if(byte == static_cast<unsigned char>('"'))
        return result;
      if(byte < 0x20)
        fail("invalid-json","Unescaped control byte in JSON string");
      if(byte != static_cast<unsigned char>('\\')) {
        result.push_back(static_cast<char>(byte));
        continue;
      }

      if(pos >= input.size())
        fail("invalid-json","JSON string ends inside an escape");
      char escape = input[pos];
      pos += 1;
      switch(escape) {
      case '"': result.push_back('"'); break;
      case '\\': result.push_back('\\'); break;
      case '/': result.push_back('/'); break;
      case 'b': result.push_back('\b'); break;
      case 'f': result.push_back('\f'); break;
      case 'n': result.push_back('\n'); break;
      case 'r': result.push_back('\r'); break;
      case 't': result.push_back('\t'); break;
      case 'u': {
        if(input.size() - pos < 4)
          fail("invalid-json","JSON Unicode escape is incomplete");
        uint32_t codePoint;
        if(!parseHexCodeUnitAt(pos,codePoint))
          fail("invalid-json","JSON Unicode escape contains a non-hex digit");
        pos += 4;
        if(codePoint >= 0xD800 && codePoint <= 0xDBFF &&
           input.size() - pos >= 6 && input[pos] == '\\' && input[pos+1] == 'u') {
          uint32_t lowSurrogate;
          if(parseHexCodeUnitAt(pos+2,lowSurrogate) && lowSurrogate >= 0xDC00 && lowSurrogate <= 0xDFFF) {
            codePoint = 0x10000 + ((codePoint-0xD800) << 10) + (lowSurrogate-0xDC00);
            pos += 6;
          }
        }
        appendUtf8(result,codePoint);
        break;
      }
      default:
        fail("invalid-json","Unknown JSON string escape");
      }
    }
    fail("invalid-json","Unterminated JSON string");
  }

  json parseInteger() {
    bool negative = false;
    if(input[pos] == '-') {
      negative = true;
      pos += 1;
      if(pos >= input.size())
        fail("invalid-json","JSON number ends after '-'");
    }

    size_t digitStart = pos;
    if(input[pos] == '0') {
      pos += 1;
      if(pos < input.size() && input[pos] >= '0' && input[pos] <= '9')
        fail("invalid-json","JSON integers cannot have leading zeroes");
    }
    else if(input[pos] >= '1' && input[pos] <= '9') {
      do {
        pos += 1;
      } while(pos < input.size() && input[pos] >= '0' && input[pos] <= '9');
    }
    else
      fail("invalid-json","Invalid JSON number");

    size_t digitEnd = pos;
    bool hasFloatingPointSyntax = false;
    if(pos+1 < input.size() && input[pos] == '.' && input[pos+1] >= '0' && input[pos+1] <= '9') {
      hasFloatingPointSyntax = true;
      pos += 2;
      while(pos < input.size() && input[pos] >= '0' && input[pos] <= '9')
        pos += 1;
    }
    if(pos < input.size() && (input[pos] == 'e' || input[pos] == 'E')) {
      size_t exponentPos = pos+1;
      if(exponentPos < input.size() && (input[exponentPos] == '+' || input[exponentPos] == '-'))
        exponentPos += 1;
      if(exponentPos < input.size() && input[exponentPos] >= '0' && input[exponentPos] <= '9') {
        hasFloatingPointSyntax = true;
        pos = exponentPos+1;
        while(pos < input.size() && input[pos] >= '0' && input[pos] <= '9')
          pos += 1;
      }
    }
    if(hasFloatingPointSyntax)
      fail("floating-point","Floating-point JSON numbers are forbidden");

    size_t normalizedStart = digitStart;
    while(normalizedStart < digitEnd && input[normalizedStart] == '0')
      normalizedStart += 1;
    size_t normalizedLength = digitEnd - normalizedStart;
    if(normalizedLength == 0) {
      normalizedStart = digitEnd-1;
      normalizedLength = 1;
    }
    static const string safeMagnitude = "9007199254740991";
    if(normalizedLength > safeMagnitude.size() ||
       (normalizedLength == safeMagnitude.size() && input.compare(normalizedStart,normalizedLength,safeMagnitude) > 0))
      fail("unsafe-integer","JSON integer is outside the safe signed range");

    int64_t magnitude = 0;
    for(size_t i = normalizedStart; i < digitEnd; i++)
      magnitude = magnitude * 10 + static_cast<int64_t>(input[i]-'0');
    int64_t value = negative ? -magnitude : magnitude;
    if(value < RulesetIdentity::SAFE_INTEGER_MIN || value > RulesetIdentity::SAFE_INTEGER_MAX)
      fail("unsafe-integer","JSON integer is outside the safe signed range");
    return json(value);
  }
};

void requireAsciiString(const string& value, bool isKey, const string& path) {
  for(unsigned char byte: value) {
    if(byte > 0x7F)
      failIdentity(isKey ? "non-ascii-key" : "non-ascii-string",(isKey ? "Non-ASCII object key at " : "Non-ASCII string at ") + path);
  }
}

void validateRestrictedValue(const json& value, const string& path, size_t depth) {
  if(depth > MAX_JSON_DEPTH)
    failIdentity("resource-limit","JSON nesting exceeds the supported depth");
  if(value.is_null() || value.is_boolean())
    return;
  if(value.is_number_float())
    failIdentity("floating-point","Floating-point value at " + path);
  if(value.is_number_unsigned()) {
    uint64_t number = value.get<uint64_t>();
    if(number > static_cast<uint64_t>(RulesetIdentity::SAFE_INTEGER_MAX))
      failIdentity("unsafe-integer","Unsafe integer at " + path);
    return;
  }
  if(value.is_number_integer()) {
    int64_t number = value.get<int64_t>();
    if(number < RulesetIdentity::SAFE_INTEGER_MIN || number > RulesetIdentity::SAFE_INTEGER_MAX)
      failIdentity("unsafe-integer","Unsafe integer at " + path);
    return;
  }
  if(value.is_string()) {
    requireAsciiString(value.get_ref<const string&>(),false,path);
    return;
  }
  if(value.is_array()) {
    for(size_t i = 0; i < value.size(); i++)
      validateRestrictedValue(value[i],path + "/" + Global::sizeToString(i),depth+1);
    return;
  }
  if(value.is_object()) {
    for(auto iter = value.begin(); iter != value.end(); ++iter) {
      requireAsciiString(iter.key(),true,path);
      validateRestrictedValue(iter.value(),path + "/" + iter.key(),depth+1);
    }
    return;
  }
  failIdentity("unsupported-json-type","Unsupported JSON value at " + path);
}

bool jsonIntegerToInt64(const json& value, int64_t& result) {
  if(value.is_number_unsigned()) {
    uint64_t unsignedValue = value.get<uint64_t>();
    if(unsignedValue > static_cast<uint64_t>(numeric_limits<int64_t>::max()))
      return false;
    result = static_cast<int64_t>(unsignedValue);
    return true;
  }
  if(value.is_number_integer()) {
    result = value.get<int64_t>();
    return true;
  }
  return false;
}

string decodeJsonPointerToken(const string& rawToken, bool& valid) {
  string token;
  valid = true;
  for(size_t i = 0; i < rawToken.size(); i++) {
    if(rawToken[i] != '~') {
      token.push_back(rawToken[i]);
      continue;
    }
    if(i+1 >= rawToken.size() || (rawToken[i+1] != '0' && rawToken[i+1] != '1')) {
      valid = false;
      return string();
    }
    token.push_back(rawToken[i+1] == '0' ? '~' : '/');
    i += 1;
  }
  return token;
}

const json* resolveLocalSchemaReference(const json& rootSchema, const string& reference) {
  if(reference == "#")
    return &rootSchema;
  if(reference.size() < 2 || reference[0] != '#' || reference[1] != '/')
    return nullptr;

  const json* current = &rootSchema;
  size_t start = 2;
  while(true) {
    size_t slash = reference.find('/',start);
    string rawToken = reference.substr(start,slash == string::npos ? string::npos : slash-start);
    bool valid;
    string token = decodeJsonPointerToken(rawToken,valid);
    if(!valid)
      return nullptr;
    if(current->is_object()) {
      auto iter = current->find(token);
      if(iter == current->end())
        return nullptr;
      current = &iter.value();
    }
    else if(current->is_array()) {
      if(token.empty())
        return nullptr;
      size_t index = 0;
      for(char c: token) {
        if(c < '0' || c > '9')
          return nullptr;
        index = index * 10 + static_cast<size_t>(c-'0');
      }
      if(index >= current->size())
        return nullptr;
      current = &(*current)[index];
    }
    else
      return nullptr;
    if(slash == string::npos)
      return current;
    start = slash+1;
  }
}

bool matchesSchemaPattern(const string& value, const string& pattern) {
  if(pattern == "^[0-9a-f]{64}$") {
    if(value.size() != 64)
      return false;
    for(char c: value) {
      if(!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
        return false;
    }
    return true;
  }
  if(pattern == "^[A-Za-z0-9][A-Za-z0-9._:/-]*$") {
    if(value.empty())
      return false;
    auto isAlphaNumeric = [](char c) {
      return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    };
    if(!isAlphaNumeric(value[0]))
      return false;
    for(char c: value) {
      if(!isAlphaNumeric(c) && c != '.' && c != '_' && c != ':' && c != '/' && c != '-')
        return false;
    }
    return true;
  }
  if(pattern == "[\\u0000-\\u001F\\u007F]") {
    for(unsigned char c: value) {
      if(c <= 0x1F || c == 0x7F)
        return true;
    }
    return false;
  }

  try {
    return regex_search(value,regex(pattern));
  }
  catch(const regex_error&) {
    return false;
  }
}

class DescriptorSchemaValidator {
public:
  explicit DescriptorSchemaValidator(const json& root)
    : rootSchema(root)
  {}

  void validate(const json& instance) const {
    string error;
    if(!matches(instance,rootSchema,"",error,0))
      failIdentity("schema-validation",error.empty() ? "Descriptor does not match ruleset-descriptor-v1" : error);
  }

private:
  const json& rootSchema;

  bool fail(const string& message, string& error) const {
    if(error.empty())
      error = message;
    return false;
  }

  bool matches(const json& instance, const json& schema, const string& path, string& error, size_t depth) const {
    if(depth > MAX_JSON_DEPTH)
      return fail("Schema validation nesting exceeds the supported depth",error);
    if(schema.is_boolean())
      return schema.get<bool>() || fail("Boolean false schema rejected " + displayPath(path),error);
    if(!schema.is_object())
      return fail("Malformed descriptor schema at " + displayPath(path),error);

    auto refIter = schema.find("$ref");
    if(refIter != schema.end()) {
      if(!refIter->is_string())
        return fail("Descriptor schema $ref is not a string",error);
      const json* target = resolveLocalSchemaReference(rootSchema,refIter->get<string>());
      if(target == nullptr)
        return fail("Descriptor schema has an unresolved or non-local $ref",error);
      if(!matches(instance,*target,path,error,depth+1))
        return false;
    }

    auto allOfIter = schema.find("allOf");
    if(allOfIter != schema.end()) {
      if(!allOfIter->is_array())
        return fail("Descriptor schema allOf is not an array",error);
      for(const json& child: *allOfIter) {
        if(!matches(instance,child,path,error,depth+1))
          return false;
      }
    }

    auto ifIter = schema.find("if");
    if(ifIter != schema.end()) {
      string ignored;
      if(matches(instance,*ifIter,path,ignored,depth+1)) {
        auto thenIter = schema.find("then");
        if(thenIter != schema.end() && !matches(instance,*thenIter,path,error,depth+1))
          return false;
      }
    }

    auto notIter = schema.find("not");
    if(notIter != schema.end()) {
      string ignored;
      if(matches(instance,*notIter,path,ignored,depth+1))
        return fail("Descriptor value matches a forbidden schema at " + displayPath(path),error);
    }

    auto constIter = schema.find("const");
    if(constIter != schema.end() && instance != *constIter)
      return fail("Descriptor constant differs at " + displayPath(path),error);

    auto enumIter = schema.find("enum");
    if(enumIter != schema.end()) {
      if(!enumIter->is_array())
        return fail("Descriptor schema enum is not an array",error);
      bool found = false;
      for(const json& candidate: *enumIter) {
        if(instance == candidate) {
          found = true;
          break;
        }
      }
      if(!found)
        return fail("Descriptor value is outside its enum at " + displayPath(path),error);
    }

    auto typeIter = schema.find("type");
    if(typeIter != schema.end()) {
      if(!typeIter->is_string())
        return fail("Descriptor schema type is not a string",error);
      const string expectedType = typeIter->get<string>();
      bool typeMatches =
        (expectedType == "object" && instance.is_object()) ||
        (expectedType == "array" && instance.is_array()) ||
        (expectedType == "string" && instance.is_string()) ||
        (expectedType == "integer" && (instance.is_number_integer() || instance.is_number_unsigned())) ||
        (expectedType == "boolean" && instance.is_boolean()) ||
        (expectedType == "null" && instance.is_null());
      if(!typeMatches)
        return fail("Descriptor type differs at " + displayPath(path),error);
    }

    if(instance.is_number_integer() || instance.is_number_unsigned()) {
      int64_t number;
      if(!jsonIntegerToInt64(instance,number))
        return fail("Descriptor integer cannot be represented safely at " + displayPath(path),error);
      auto minimumIter = schema.find("minimum");
      if(minimumIter != schema.end()) {
        int64_t minimum;
        if(!jsonIntegerToInt64(*minimumIter,minimum) || number < minimum)
          return fail("Descriptor integer is below its minimum at " + displayPath(path),error);
      }
      auto maximumIter = schema.find("maximum");
      if(maximumIter != schema.end()) {
        int64_t maximum;
        if(!jsonIntegerToInt64(*maximumIter,maximum) || number > maximum)
          return fail("Descriptor integer is above its maximum at " + displayPath(path),error);
      }
    }

    if(instance.is_string()) {
      const string& text = instance.get_ref<const string&>();
      auto minLengthIter = schema.find("minLength");
      if(minLengthIter != schema.end()) {
        int64_t minLength;
        if(!jsonIntegerToInt64(*minLengthIter,minLength) || minLength < 0 || text.size() < static_cast<size_t>(minLength))
          return fail("Descriptor string is shorter than its minimum at " + displayPath(path),error);
      }
      auto maxLengthIter = schema.find("maxLength");
      if(maxLengthIter != schema.end()) {
        int64_t maxLength;
        if(!jsonIntegerToInt64(*maxLengthIter,maxLength) || maxLength < 0 || text.size() > static_cast<size_t>(maxLength))
          return fail("Descriptor string is longer than its maximum at " + displayPath(path),error);
      }
      auto patternIter = schema.find("pattern");
      if(patternIter != schema.end()) {
        if(!patternIter->is_string() || !matchesSchemaPattern(text,patternIter->get<string>()))
          return fail("Descriptor string does not match its pattern at " + displayPath(path),error);
      }
    }

    if(instance.is_object()) {
      auto requiredIter = schema.find("required");
      if(requiredIter != schema.end()) {
        if(!requiredIter->is_array())
          return fail("Descriptor schema required is not an array",error);
        for(const json& requiredKey: *requiredIter) {
          if(!requiredKey.is_string())
            return fail("Descriptor schema required contains a non-string",error);
          if(instance.find(requiredKey.get<string>()) == instance.end())
            return fail("Descriptor is missing required field " + childPath(path,requiredKey.get<string>()),error);
        }
      }

      auto propertiesIter = schema.find("properties");
      if(propertiesIter != schema.end()) {
        if(!propertiesIter->is_object())
          return fail("Descriptor schema properties is not an object",error);
        for(auto iter = propertiesIter->begin(); iter != propertiesIter->end(); ++iter) {
          auto valueIter = instance.find(iter.key());
          if(valueIter != instance.end() && !matches(valueIter.value(),iter.value(),childPath(path,iter.key()),error,depth+1))
            return false;
        }
      }

      auto additionalIter = schema.find("additionalProperties");
      if(additionalIter != schema.end() && additionalIter->is_boolean() && !additionalIter->get<bool>()) {
        for(auto iter = instance.begin(); iter != instance.end(); ++iter) {
          if(propertiesIter == schema.end() || propertiesIter->find(iter.key()) == propertiesIter->end())
            return fail("Descriptor contains unknown field " + childPath(path,iter.key()),error);
        }
      }
    }

    return true;
  }

  static string childPath(const string& path, const string& key) {
    return path + "/" + key;
  }

  static string displayPath(const string& path) {
    return path.empty() ? "/" : path;
  }
};

void validateSchemaReferences(const json& value) {
  if(value.is_object()) {
    for(auto iter = value.begin(); iter != value.end(); ++iter) {
      if(iter.key() == "$dynamicRef")
        failIdentity("schema-validation","Dynamic schema references are forbidden");
      if(iter.key() == "$ref") {
        if(!iter.value().is_string())
          failIdentity("schema-validation","Schema $ref must be a string");
        const string reference = iter.value().get<string>();
        if(reference.empty() || reference[0] != '#')
          failIdentity("schema-validation","Only local descriptor schema references are allowed");
      }
      validateSchemaReferences(iter.value());
    }
  }
  else if(value.is_array()) {
    for(const json& item: value)
      validateSchemaReferences(item);
  }
}

void validateDescriptorSchemaMetadata(const json& schema) {
  if(!schema.is_object())
    failIdentity("schema-validation","Descriptor schema root must be an object");
  auto dialect = schema.find("$schema");
  auto id = schema.find("$id");
  if(dialect == schema.end() || !dialect->is_string() || dialect->get<string>() != "https://json-schema.org/draft/2020-12/schema")
    failIdentity("schema-validation","Descriptor schema must use JSON Schema Draft 2020-12");
  if(id == schema.end() || !id->is_string() || id->get<string>() != RulesetIdentity::DESCRIPTOR_SCHEMA_ID)
    failIdentity("schema-validation","Descriptor schema has the wrong $id");
  validateSchemaReferences(schema);
}

void validateDescriptorSemantics(const json& descriptor, bool requirePublic) {
  const json& identity = descriptor.at("identity");
  if(identity.at("rulesetId").get<string>() != RulesetIdentity::PUBLIC_RULESET_ID)
    failIdentity("descriptor-validation","rulesetId is not mutago.collapse-go");
  if(requirePublic && identity.at("semanticVersion").get<string>() != RulesetIdentity::PUBLIC_SEMANTIC_VERSION)
    failIdentity("descriptor-validation","Public semantic version is not 0.1.0-draft");
  if(identity.at("internalVariantEnumIsPublicIdentity").get<bool>() ||
     identity.at("repositorySlugIsPublicIdentity").get<bool>() ||
     identity.at("runtimeModeLabelsArePublicIdentity").get<bool>())
    failIdentity("descriptor-validation","Internal enums, repository slugs, and runtime labels are not public identity");

  const json& canonicalization = descriptor.at("canonicalization");
  if(canonicalization.at("profile").get<string>() != RulesetIdentity::CANONICALIZATION_PROFILE ||
     !canonicalization.at("rfc8785Base").get<bool>() ||
     canonicalization.at("characterEncoding").get<string>() != "UTF-8" ||
     canonicalization.at("objectKeyOrder").get<string>() != "UTF-16-CODE-UNIT-LEXICOGRAPHIC" ||
     canonicalization.at("stringDomain").get<string>() != "ASCII" ||
     canonicalization.at("safeIntegerMinimum").get<int64_t>() != RulesetIdentity::SAFE_INTEGER_MIN ||
     canonicalization.at("safeIntegerMaximum").get<int64_t>() != RulesetIdentity::SAFE_INTEGER_MAX ||
     !canonicalization.at("rejectDuplicateKeys").get<bool>() ||
     !canonicalization.at("rejectFloatingPoint").get<bool>() ||
     !canonicalization.at("rejectNonAsciiStrings").get<bool>() ||
     !canonicalization.at("rejectNonAsciiObjectKeys").get<bool>() ||
     !canonicalization.at("rejectUnknownDescriptorFields").get<bool>() ||
     canonicalization.at("digestAlgorithm").get<string>() != "SHA-256" ||
     canonicalization.at("digestEncoding").get<string>() != "LOWERCASE_HEX")
    failIdentity("descriptor-validation","Descriptor canonicalization profile differs from the frozen contract");

  const json& initialState = descriptor.at("initialState");
  const json& boardPolicy = descriptor.at("boardPolicy");
  if(initialState.at("boardSize") != boardPolicy.at("selectedBoardSize"))
    failIdentity("descriptor-validation","Selected board size does not match the initial state");
  if(!initialState.at("initialPSKSeed").get<bool>() || initialState.at("initialPSKEntryIndex").get<int64_t>() != 0)
    failIdentity("descriptor-validation","Initial empty occupancy must be PSK history entry zero");

  const json& psk = descriptor.at("positionalSuperko");
  if(!psk.at("initialPSKSeed").get<bool>() || psk.at("initialEmptyOccupancyEntryIndex").get<int64_t>() != 0)
    failIdentity("descriptor-validation","Initial empty occupancy must be PSK history entry zero");

  const json& actionSpace = descriptor.at("actionSpace");
  if(actionSpace.at("layout").get<string>() != "KIND_MAJOR" ||
     actionSpace.at("flatActionCount").get<int64_t>() != 1445 ||
     actionSpace.at("passActionId").get<int64_t>() != 1444)
    failIdentity("descriptor-validation","Action space is not the frozen 1445-way kind-major layout");

  if(descriptor.at("deadStoneHandling").at("mvpShortcutStatus").get<string>() != "DEFERRED")
    failIdentity("descriptor-validation","MVP dead-stone shortcut must remain deferred");

  if(requirePublic) {
    if(initialState.at("boardSize").get<int64_t>() != 19)
      failIdentity("descriptor-validation","Public descriptor must select the official 19x19 board");
    json officialQuota = {
      {"IMMORTAL",1},
      {"DOUBLE_START",1},
      {"EIGHTWAY",1},
    };
    json officialByPlayer = {
      {"BLACK",officialQuota},
      {"WHITE",officialQuota},
    };
    if(descriptor.at("quotas").at("initialByPlayer") != officialByPlayer)
      failIdentity("descriptor-validation","Public complete per-player quota vectors are not 1/1/1");
  }
}

}

RulesetIdentity::RulesetIdentity(
  const string& identityRulesetId,
  const string& identitySemanticVersion,
  const string& identityDescriptorSha256,
  const string& identityCanonicalDescriptorBytes
)
  : rulesetId(identityRulesetId),
    semanticVersion(identitySemanticVersion),
    descriptorSha256(identityDescriptorSha256),
    canonicalDescriptorBytes(identityCanonicalDescriptorBytes)
{}

json RulesetIdentity::parseRestrictedJson(const string& rawJson) {
  validateUtf8(rawJson);
  RestrictedJsonParser parser(rawJson);
  json value = parser.parse();
  validateRestrictedValue(value,"/",0);
  return value;
}

string RulesetIdentity::canonicalizeRestrictedJson(const char* rawJson) {
  return canonicalizeRestrictedJson(string(rawJson));
}

string RulesetIdentity::canonicalizeRestrictedJson(const string& rawJson) {
  return canonicalizeRestrictedJson(parseRestrictedJson(rawJson));
}

string RulesetIdentity::canonicalizeRestrictedJson(const json& value) {
  validateRestrictedValue(value,"/",0);
  try {
    return value.dump();
  }
  catch(const nlohmann::detail::exception& e) {
    failIdentity("invalid-json",string("Could not canonicalize JSON value: ") + e.what());
  }
}

string RulesetIdentity::sha256Hex(const string& bytes) {
  char hash[65];
  SHA2::get256(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size(),hash);
  return string(hash);
}

RulesetIdentity RulesetIdentity::fromDescriptorJson(
  const string& descriptorJson,
  const string& descriptorSchemaJson,
  bool requirePublic
) {
  json descriptor = parseRestrictedJson(descriptorJson);
  json descriptorSchema = parseRestrictedJson(descriptorSchemaJson);
  string canonicalSchema = canonicalizeRestrictedJson(descriptorSchema);
  if(sha256Hex(canonicalSchema) != DESCRIPTOR_SCHEMA_SHA256)
    failIdentity("schema-validation","Descriptor schema does not match the frozen ruleset-descriptor-v1 source");
  validateDescriptorSchemaMetadata(descriptorSchema);
  DescriptorSchemaValidator(descriptorSchema).validate(descriptor);
  validateDescriptorSemantics(descriptor,requirePublic);

  string canonical = canonicalizeRestrictedJson(descriptor);
  string digest = sha256Hex(canonical);
  const string semanticVersion = descriptor.at("identity").at("semanticVersion").get<string>();
  if(semanticVersion == PUBLIC_SEMANTIC_VERSION && digest != PUBLIC_DESCRIPTOR_SHA256)
    failIdentity("descriptor-validation","The official semantic version may only identify the assigned public descriptor");
  if(requirePublic && digest != PUBLIC_DESCRIPTOR_SHA256)
    failIdentity("descriptor-validation","Public descriptor canonical SHA-256 differs from the assigned identity");

  return RulesetIdentity(
    descriptor.at("identity").at("rulesetId").get<string>(),
    semanticVersion,
    digest,
    canonical
  );
}

const string& RulesetIdentity::getRulesetId() const {
  return rulesetId;
}

const string& RulesetIdentity::getSemanticVersion() const {
  return semanticVersion;
}

const string& RulesetIdentity::getDescriptorSha256() const {
  return descriptorSha256;
}

const string& RulesetIdentity::getCanonicalDescriptorBytes() const {
  return canonicalDescriptorBytes;
}

json RulesetIdentity::toJson() const {
  json value;
  value["rulesetId"] = rulesetId;
  value["semanticVersion"] = semanticVersion;
  value["descriptorSha256"] = descriptorSha256;
  return value;
}

bool RulesetIdentity::operator==(const RulesetIdentity& other) const {
  return rulesetId == other.rulesetId &&
    semanticVersion == other.semanticVersion &&
    descriptorSha256 == other.descriptorSha256;
}

bool RulesetIdentity::operator!=(const RulesetIdentity& other) const {
  return !(*this == other);
}
