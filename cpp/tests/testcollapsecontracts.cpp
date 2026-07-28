#include "../tests/tests.h"

#include <limits>

#include "../core/fileutils.h"
#include "../game/gameaction.h"
#include "../game/rulesetidentity.h"

using nlohmann::json;
using namespace std;
using namespace TestCommon;

namespace {

void expectGameActionError(const string& expectedCode, const function<void()>& operation) {
  try {
    operation();
  }
  catch(const GameActionError& error) {
    if(error.getCode() != expectedCode)
      throw StringError("Expected GameAction error " + expectedCode + ", got " + error.getCode() + ": " + error.what());
    return;
  }
  throw StringError("Expected GameAction error " + expectedCode + ", but operation succeeded");
}

void expectRulesetIdentityError(const string& expectedCode, const function<void()>& operation) {
  try {
    operation();
  }
  catch(const RulesetIdentityError& error) {
    if(error.getCode() != expectedCode)
      throw StringError("Expected RulesetIdentity error " + expectedCode + ", got " + error.getCode() + ": " + error.what());
    return;
  }
  throw StringError("Expected RulesetIdentity error " + expectedCode + ", but operation succeeded");
}

void expectStringErrorContaining(const string& expectedText, const function<void()>& operation) {
  try {
    operation();
  }
  catch(const StringError& error) {
    if(string(error.what()).find(expectedText) == string::npos)
      throw StringError("Expected error containing '" + expectedText + "', got: " + error.what());
    return;
  }
  throw StringError("Expected StringError containing '" + expectedText + "', but operation succeeded");
}

const vector<string>& mandatoryContractArtifactRelativePaths() {
  static const vector<string> paths = {
    "rulesets/collapse-go/vectors/canonicalization-v1.json",
    "schemas/source/action-v1.schema.json",
    "rulesets/collapse-go/vectors/action-v1.json",
    "rulesets/collapse-go/descriptor-v0.1.0-draft.json",
    "schemas/source/ruleset-descriptor-v1.schema.json",
    "schemas/source/semantic-projection-v1.schema.json",
    "schemas/source/conformance-fixture-v1.schema.json",
    "schemas/source/mismatch-bundle-v1.schema.json",
    "rulesets/collapse-go/vectors/public-identity-v1.json",
    "rulesets/collapse-go/vectors/descriptor-invalid-v1.json",
  };
  return paths;
}

map<string,string> requireContractArtifacts(const function<bool(const string&,string&)>& locator) {
  map<string,string> resolved;
  vector<string> missing;
  for(const string& relativePath: mandatoryContractArtifactRelativePaths()) {
    string path;
    if(locator(relativePath,path))
      resolved[relativePath] = path;
    else
      missing.push_back(relativePath);
  }
  if(!missing.empty()) {
    string message = "Missing mandatory Collapse Go M0 contract artifact";
    if(missing.size() != 1)
      message += "s";
    message += ": ";
    for(size_t i = 0; i < missing.size(); i++) {
      if(i > 0)
        message += ", ";
      message += missing[i];
    }
    throw StringError(message);
  }
  return resolved;
}

bool findRepoFile(const string& relativePath, string& path) {
#ifdef MUTAGO_REPOSITORY_ROOT
  string configuredCandidate = string(MUTAGO_REPOSITORY_ROOT) + "/" + relativePath;
  if(FileUtils::exists(configuredCandidate)) {
    path = configuredCandidate;
    return true;
  }
  return false;
#else
  string sourceFile = __FILE__;
  std::replace(sourceFile.begin(),sourceFile.end(),'\\','/');
  const string sourceMarker = "cpp/tests/testcollapsecontracts.cpp";
  size_t marker = sourceFile.rfind(sourceMarker);
  if(marker != string::npos) {
    string candidate = sourceFile.substr(0,marker) + relativePath;
    if(FileUtils::exists(candidate)) {
      path = candidate;
      return true;
    }
  }

  string prefix;
  for(int i = 0; i < 9; i++) {
    string candidate = prefix + relativePath;
    if(FileUtils::exists(candidate)) {
      path = candidate;
      return true;
    }
    prefix = "../" + prefix;
  }
  return false;
#endif
}

int lowercaseHexDigitValue(char c) {
  if(c >= '0' && c <= '9')
    return c-'0';
  if(c >= 'a' && c <= 'f')
    return c-'a'+10;
  return -1;
}

string decodeHex(const string& hex) {
  if(hex.size() % 2 != 0)
    throw StringError("Odd-length hex in contract vector");
  string bytes;
  bytes.reserve(hex.size()/2);
  for(size_t i = 0; i < hex.size(); i += 2) {
    int high = lowercaseHexDigitValue(hex[i]);
    int low = lowercaseHexDigitValue(hex[i+1]);
    if(high < 0 || low < 0)
      throw StringError("Contract vector hex must use lowercase digits");
    bytes.push_back(static_cast<char>((high << 4) | low));
  }
  return bytes;
}

void requireExactKeys(const json& value, const vector<string>& expectedKeys, const string& context) {
  if(!value.is_object())
    throw StringError(context + " must be an object");
  set<string> expected(expectedKeys.begin(),expectedKeys.end());
  set<string> actual;
  for(auto iter = value.begin(); iter != value.end(); ++iter)
    actual.insert(iter.key());
  if(actual != expected)
    throw StringError(context + " has an unexpected key set");
}

int64_t requireExactInt64(const json& value, const string& context) {
  if(!value.is_number_integer())
    throw StringError(context + " must be an integer");
  if(value.is_number_unsigned()) {
    uint64_t parsed = value.get<uint64_t>();
    if(parsed > static_cast<uint64_t>(numeric_limits<int64_t>::max()))
      throw StringError(context + " is outside the signed 64-bit range");
    return static_cast<int64_t>(parsed);
  }
  return value.get<int64_t>();
}

int requireExactIntInRange(const json& value, int minimum, int maximum, const string& context) {
  int64_t parsed = requireExactInt64(value,context);
  if(parsed < minimum || parsed > maximum)
    throw StringError(context + " is outside the required range");
  return static_cast<int>(parsed);
}

int requireSupportedBoardSize(const json& value, const string& context) {
  int boardSize = requireExactIntInRange(value,9,19,context);
  if(boardSize != 9 && boardSize != 13 && boardSize != 19)
    throw StringError(context + " must be 9, 13, or 19");
  return boardSize;
}

string parentDirectory(const string& path) {
  size_t separator = path.find_last_of("/\\");
  if(separator == string::npos)
    throw StringError("Contract artifact path has no parent directory: " + path);
  return path.substr(0,separator);
}

set<string> filesWithSuffix(const string& directory, const string& suffix) {
  set<string> files;
  for(const string& fileName: FileUtils::listFiles(directory)) {
    if(Global::isSuffix(fileName,suffix))
      files.insert(fileName);
  }
  return files;
}

void requireExactFileSet(const set<string>& actual, const set<string>& expected, const string& context) {
  if(actual == expected)
    return;
  string message = context + " file set differs; actual:";
  for(const string& fileName: actual)
    message += " " + fileName;
  throw StringError(message);
}

void requireExactContractArtifactSets(const map<string,string>& artifacts) {
  const set<string> expectedSchemas = {
    "action-v1.schema.json",
    "conformance-fixture-v1.schema.json",
    "mismatch-bundle-v1.schema.json",
    "ruleset-descriptor-v1.schema.json",
    "semantic-projection-v1.schema.json",
  };
  const set<string> expectedVectors = {
    "action-v1.json",
    "canonicalization-v1.json",
    "descriptor-invalid-v1.json",
    "public-identity-v1.json",
  };
  const string schemaDirectory = parentDirectory(artifacts.at("schemas/source/action-v1.schema.json"));
  const string vectorDirectory = parentDirectory(artifacts.at("rulesets/collapse-go/vectors/action-v1.json"));
  requireExactFileSet(filesWithSuffix(schemaDirectory,".schema.json"),expectedSchemas,"Collapse Go M0 schema");
  requireExactFileSet(filesWithSuffix(vectorDirectory,".json"),expectedVectors,"Collapse Go M0 vector");
}

vector<string> caseIds(const json& cases) {
  if(!cases.is_array())
    throw StringError("Contract vector cases must be an array");
  vector<string> ids;
  set<string> unique;
  for(const json& vectorCase: cases) {
    string id = vectorCase.at("id").get<string>();
    if(!unique.insert(id).second)
      throw StringError("Duplicate contract vector case ID: " + id);
    ids.push_back(id);
  }
  return ids;
}

void requireCaseIds(const json& cases, const vector<string>& expectedIds, const string& context) {
  if(caseIds(cases) != expectedIds)
    throw StringError(context + " case inventory differs from the frozen vector");
}

string decodePointerToken(const string& raw) {
  string token;
  for(size_t i = 0; i < raw.size(); i++) {
    if(raw[i] != '~') {
      token.push_back(raw[i]);
      continue;
    }
    if(i+1 >= raw.size() || (raw[i+1] != '0' && raw[i+1] != '1'))
      throw StringError("Invalid JSON pointer in descriptor vector");
    token.push_back(raw[i+1] == '0' ? '~' : '/');
    i += 1;
  }
  return token;
}

vector<string> pointerParts(const string& pointer) {
  if(pointer.empty() || pointer[0] != '/')
    throw StringError("Descriptor vector pointer must be nonempty and start with '/'");
  vector<string> parts;
  size_t start = 1;
  while(true) {
    size_t slash = pointer.find('/',start);
    parts.push_back(decodePointerToken(pointer.substr(start,slash == string::npos ? string::npos : slash-start)));
    if(slash == string::npos)
      return parts;
    start = slash+1;
  }
}

json mutateDescriptor(const json& base, const json& vectorCase) {
  json result = base;
  vector<string> parts = pointerParts(vectorCase.at("jsonPointer").get<string>());
  json* parent = &result;
  for(size_t i = 0; i+1 < parts.size(); i++) {
    auto iter = parent->find(parts[i]);
    if(iter == parent->end() || !iter->is_object())
      throw StringError("Descriptor vector pointer crosses a missing or scalar value");
    parent = &iter.value();
  }

  const string& finalPart = parts.back();
  const string operation = vectorCase.at("operation").get<string>();
  if(operation == "ADD") {
    if(parent->find(finalPart) != parent->end())
      throw StringError("Descriptor ADD vector target already exists");
    (*parent)[finalPart] = vectorCase.at("value");
  }
  else if(operation == "REPLACE") {
    if(parent->find(finalPart) == parent->end())
      throw StringError("Descriptor REPLACE vector target is missing");
    (*parent)[finalPart] = vectorCase.at("value");
  }
  else if(operation == "REMOVE") {
    if(parent->erase(finalPart) != 1)
      throw StringError("Descriptor REMOVE vector target is missing");
  }
  else
    throw StringError("Unknown descriptor vector mutation operation");
  return result;
}

vector<string> expectedOffBoardCaseIds() {
  const string kindNames[4] = {"normal","immortal","double_start","eightway"};
  vector<string> ids;
  for(int boardSize: {9,13,19}) {
    for(const string& kind: kindNames) {
      ids.push_back("semantic-n" + Global::intToString(boardSize) + "-" + kind + "-x-negative");
      ids.push_back("semantic-n" + Global::intToString(boardSize) + "-" + kind + "-x-too-large");
      ids.push_back("semantic-n" + Global::intToString(boardSize) + "-" + kind + "-y-negative");
      ids.push_back("semantic-n" + Global::intToString(boardSize) + "-" + kind + "-y-too-large");
    }
  }
  for(int boardSize: {9,13}) {
    for(const string& kind: kindNames) {
      ids.push_back("canvas-footprint-n" + Global::intToString(boardSize) + "-" + kind + "-left");
      ids.push_back("canvas-footprint-n" + Global::intToString(boardSize) + "-" + kind + "-right");
      ids.push_back("canvas-footprint-n" + Global::intToString(boardSize) + "-" + kind + "-top");
      ids.push_back("canvas-footprint-n" + Global::intToString(boardSize) + "-" + kind + "-bottom");
    }
  }
  for(const string& kind: kindNames) {
    ids.push_back("canvas-" + kind + "-x-negative");
    ids.push_back("canvas-" + kind + "-x-too-large");
    ids.push_back("canvas-" + kind + "-y-negative");
    ids.push_back("canvas-" + kind + "-y-too-large");
  }
  const string trailingIds[9] = {
    "semantic-x-noninteger",
    "semantic-board-unsupported",
    "semantic-board-boolean",
    "canvas-x-noninteger",
    "decode-noninteger",
    "decode-boolean",
    "decode-negative",
    "decode-too-large",
    "unknown-kind",
  };
  ids.insert(ids.end(),trailingIds,trailingIds+9);
  return ids;
}

vector<string> expectedD4CaseIds() {
  const string kindNames[4] = {"normal","immortal","double_start","eightway"};
  vector<string> ids;
  for(int boardSize: {9,13,19}) {
    for(const string& kind: kindNames) {
      for(int symmetry = 0; symmetry < 8; symmetry++)
        ids.push_back("d4-n" + Global::intToString(boardSize) + "-" + kind + "-s" + Global::intToString(symmetry));
    }
  }
  for(int symmetry = 0; symmetry < 8; symmetry++)
    ids.push_back("d4-pass-s" + Global::intToString(symmetry));
  return ids;
}

json actionCodecRecords() {
  json records = json::array();
  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    GameAction action = GameAction::decode(actionId);
    json record = json::object();
    record["actionId"] = actionId;
    record["kind"] = GameAction::kindToString(action.getKind());
    record["canvasX"] = action.isPass() ? json(nullptr) : json(action.getCanvasX());
    record["canvasY"] = action.isPass() ? json(nullptr) : json(action.getCanvasY());
    records.push_back(record);
  }
  return records;
}

json centeredMappingRecords(int boardSize) {
  json records = json::array();
  const GameActionKind kinds[4] = {
    GameActionKind::NORMAL,
    GameActionKind::IMMORTAL,
    GameActionKind::DOUBLE_START,
    GameActionKind::EIGHTWAY,
  };
  for(int y = 0; y < boardSize; y++) {
    for(int x = 0; x < boardSize; x++) {
      json actionIds = json::object();
      for(GameActionKind kind: kinds) {
        GameAction action = GameAction::fromBoard(kind,boardSize,x,y);
        actionIds[GameAction::kindToString(kind)] = action.getActionId();
      }
      GameAction normal = GameAction::fromBoard(GameActionKind::NORMAL,boardSize,x,y);
      json record = json::object();
      record["semanticX"] = x;
      record["semanticY"] = y;
      record["semanticPointIndex"] = boardSize*y+x;
      record["canvasX"] = normal.getCanvasX();
      record["canvasY"] = normal.getCanvasY();
      record["canvasPointIndex"] = GameAction::CANVAS_SIZE*normal.getCanvasY()+normal.getCanvasX();
      record["actionIds"] = actionIds;
      records.push_back(record);
    }
  }
  return records;
}

void boardFootprintRecords(int boardSize, json& accepted, json& rejected) {
  accepted = json::array();
  rejected = json::array();
  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    GameAction action = GameAction::decode(actionId);
    if(action.isInBoardFootprint(boardSize)) {
      json record = json::object();
      record["actionId"] = actionId;
      record["kind"] = GameAction::kindToString(action.getKind());
      record["semanticX"] = action.isPass() ? json(nullptr) : json(action.getBoardX(boardSize));
      record["semanticY"] = action.isPass() ? json(nullptr) : json(action.getBoardY(boardSize));
      accepted.push_back(record);
    }
    else {
      json record = json::object();
      record["actionId"] = actionId;
      record["kind"] = GameAction::kindToString(action.getKind());
      record["expectedErrorCode"] = "point-off-board";
      rejected.push_back(record);
    }
  }
}

void runMandatoryArtifactFailureTests() {
  const vector<string>& requiredPaths = mandatoryContractArtifactRelativePaths();
  for(const string& missingPath: requiredPaths) {
    expectStringErrorContaining(missingPath,[missingPath]() {
      requireContractArtifacts([missingPath](const string& relativePath, string& resolvedPath) {
        if(relativePath == missingPath)
          return false;
        resolvedPath = "/virtual-repository/" + relativePath;
        return true;
      });
    });
  }

  string allMissingMessage = "Missing mandatory Collapse Go M0 contract artifacts: ";
  for(size_t i = 0; i < requiredPaths.size(); i++) {
    if(i > 0)
      allMissingMessage += ", ";
    allMissingMessage += requiredPaths[i];
  }
  expectStringErrorContaining(allMissingMessage,[]() {
    requireContractArtifacts([](const string&, string&) noexcept {
      return false;
    });
  });

  map<string,string> resolved = requireContractArtifacts([](const string& relativePath, string& resolvedPath) {
    resolvedPath = "/virtual-repository/" + relativePath;
    return true;
  });
  testAssert(resolved.size() == requiredPaths.size());
  for(const string& relativePath: requiredPaths)
    testAssert(resolved.at(relativePath) == "/virtual-repository/" + relativePath);

  const set<string> expected = {"a.schema.json","b.schema.json"};
  requireExactFileSet(expected,expected,"Synthetic contract");
  expectStringErrorContaining("Synthetic contract file set differs",[expected]() {
    set<string> unexpected = expected;
    unexpected.insert("unexpected.schema.json");
    requireExactFileSet(unexpected,expected,"Synthetic contract");
  });
  expectStringErrorContaining("Synthetic contract file set differs",[expected]() {
    set<string> missing = {"a.schema.json"};
    requireExactFileSet(missing,expected,"Synthetic contract");
  });
}

void runEmbeddedGameActionTests() {
  expectStringErrorContaining("must be an integer",[]() {
    requireExactIntInRange(json(false),0,7,"Synthetic symmetryId");
  });
  expectStringErrorContaining("outside the required range",[]() {
    requireSupportedBoardSize(json(4294967305LL),"Synthetic boardSize");
  });

  testAssert(GameAction::CANVAS_SIZE == 19);
  testAssert(GameAction::CANVAS_POINT_COUNT == 361);
  testAssert(GameAction::KIND_STRIDE == 361);
  testAssert(GameAction::FLAT_ACTION_COUNT == 1445);
  testAssert(GameAction::PASS_ACTION_ID == 1444);

  const GameActionKind kinds[4] = {
    GameActionKind::NORMAL,
    GameActionKind::IMMORTAL,
    GameActionKind::DOUBLE_START,
    GameActionKind::EIGHTWAY,
  };
  const string kindNames[4] = {"NORMAL","IMMORTAL","DOUBLE_START","EIGHTWAY"};
  for(int kindCode = 0; kindCode < 4; kindCode++) {
    testAssert(GameAction::kindCode(kinds[kindCode]) == kindCode);
    testAssert(GameAction::kindToString(kinds[kindCode]) == kindNames[kindCode]);
    testAssert(GameAction::parseKind(kindNames[kindCode]) == kinds[kindCode]);
  }
  testAssert(GameAction::parseKind("PASS") == GameActionKind::PASS);
  testAssert(GameAction::kindToString(GameActionKind::PASS) == "PASS");
  expectGameActionError("unknown-action-kind",[]() { GameAction::parseKind("UNKNOWN"); });
  expectGameActionError("non-canonical-action",[]() { GameAction::fromCanvas(GameActionKind::PASS,0,0); });
  expectGameActionError("unknown-action-kind",[]() {
    GameAction::fromCanvas(json("PASS"),json(0),json(0));
  });
  expectGameActionError("unknown-action-kind",[]() {
    GameAction::fromBoard(json("PASS"),json(9),json(0),json(0));
  });

  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    GameAction action = GameAction::decode(actionId);
    testAssert(action.getActionId() == actionId);
    testAssert(GameAction::ofJson(action.toJson()) == action);
    if(actionId == GameAction::PASS_ACTION_ID) {
      testAssert(action.isPass());
      testAssert(action.getCanvasX() == -1);
      testAssert(action.getCanvasY() == -1);
    }
    else {
      testAssert(!action.isPass());
      int expectedCode = actionId / GameAction::KIND_STRIDE;
      int expectedPoint = actionId % GameAction::KIND_STRIDE;
      testAssert(GameAction::kindCode(action.getKind()) == expectedCode);
      testAssert(action.getCanvasX() == expectedPoint % GameAction::CANVAS_SIZE);
      testAssert(action.getCanvasY() == expectedPoint / GameAction::CANVAS_SIZE);
      testAssert(GameAction::fromCanvas(action.getKind(),action.getCanvasX(),action.getCanvasY()) == action);
    }
  }
  expectGameActionError("action-id-out-of-range",[]() { GameAction::decode(-1); });
  expectGameActionError("action-id-out-of-range",[]() { GameAction::decode(1445); });
  expectGameActionError("point-off-board",[]() { GameAction::fromCanvas(GameActionKind::NORMAL,-1,0); });
  expectGameActionError("point-off-board",[]() { GameAction::fromCanvas(GameActionKind::NORMAL,19,0); });

  json safeIntegerMaximum = static_cast<int64_t>(9007199254740991LL);
  json safeIntegerWrappingToZero = static_cast<uint64_t>(4294967296ULL);
  json safeIntegerWrappingToNine = static_cast<uint64_t>(4294967305ULL);
  json unsafeInteger = static_cast<uint64_t>(9007199254740992ULL);
  expectGameActionError("point-off-board",[&safeIntegerMaximum]() {
    GameAction::fromCanvas(json("NORMAL"),safeIntegerMaximum,json(0));
  });
  expectGameActionError("unsupported-board-size",[&safeIntegerMaximum]() {
    GameAction::fromBoard(json("NORMAL"),safeIntegerMaximum,json(0),json(0));
  });
  expectGameActionError("point-off-board",[&safeIntegerMaximum]() {
    GameAction::fromBoard(json("NORMAL"),json(9),safeIntegerMaximum,json(0));
  });
  expectGameActionError("action-id-out-of-range",[&safeIntegerMaximum]() {
    GameAction::decode(safeIntegerMaximum);
  });
  expectGameActionError("action-id-out-of-range",[&safeIntegerMaximum]() {
    GameAction::decodeForBoard(safeIntegerMaximum,json(9));
  });
  expectGameActionError("unsupported-board-size",[&safeIntegerMaximum]() {
    GameAction::decodeForBoard(json(0),safeIntegerMaximum);
  });
  expectGameActionError("point-off-board",[&safeIntegerWrappingToZero]() {
    GameAction::fromCanvas(json("NORMAL"),safeIntegerWrappingToZero,json(0));
  });
  expectGameActionError("unsupported-board-size",[&safeIntegerWrappingToNine]() {
    GameAction::fromBoard(json("NORMAL"),safeIntegerWrappingToNine,json(0),json(0));
  });
  expectGameActionError("point-off-board",[&safeIntegerWrappingToZero]() {
    GameAction::fromBoard(json("NORMAL"),json(9),safeIntegerWrappingToZero,json(0));
  });
  expectGameActionError("action-id-out-of-range",[&safeIntegerWrappingToZero]() {
    GameAction::decode(safeIntegerWrappingToZero);
  });
  expectGameActionError("action-id-out-of-range",[&safeIntegerWrappingToZero]() {
    GameAction::decodeForBoard(safeIntegerWrappingToZero,json(19));
  });
  expectGameActionError("unsupported-board-size",[&safeIntegerWrappingToNine]() {
    GameAction::decodeForBoard(json(0),safeIntegerWrappingToNine);
  });
  expectGameActionError("unsafe-integer",[&unsafeInteger]() { GameAction::decode(unsafeInteger); });

  for(int boardSize: {9,13,19}) {
    int offset = GameAction::boardOffset(boardSize);
    testAssert(offset == (19-boardSize)/2);
    for(int y = 0; y < boardSize; y++) {
      for(int x = 0; x < boardSize; x++) {
        for(GameActionKind kind: kinds) {
          GameAction action = GameAction::fromBoard(kind,boardSize,x,y);
          int expected = GameAction::KIND_STRIDE*GameAction::kindCode(kind) +
            GameAction::CANVAS_SIZE*(y+offset) + x+offset;
          testAssert(action.getActionId() == expected);
          testAssert(action.isInBoardFootprint(boardSize));
          testAssert(action.getBoardX(boardSize) == x);
          testAssert(action.getBoardY(boardSize) == y);
          testAssert(GameAction::decodeForBoard(expected,boardSize) == action);
        }
      }
    }
    GameAction pass = GameAction::decodeForBoard(GameAction::PASS_ACTION_ID,boardSize);
    testAssert(pass.isPass());
    testAssert(pass.getBoardX(boardSize) == -1);
    testAssert(pass.getBoardY(boardSize) == -1);
  }
  expectGameActionError("unsupported-board-size",[]() { GameAction::boardOffset(11); });
  expectGameActionError("point-off-board",[]() { GameAction::fromBoard(GameActionKind::NORMAL,9,-1,0); });
  expectGameActionError("point-off-board",[]() { GameAction::fromBoard(GameActionKind::NORMAL,13,13,0); });
  expectGameActionError("point-off-board",[]() { GameAction::decodeForBoard(99,9); });
  expectGameActionError("point-off-board",[]() { GameAction::decodeForBoard(59,13); });

  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    GameAction action = GameAction::decode(actionId);
    for(int symmetry = 0; symmetry < GameAction::SYMMETRY_COUNT; symmetry++) {
      GameAction transformed = action.transformed(symmetry);
      testAssert(transformed.getKind() == action.getKind());
      testAssert(transformed.transformed(GameAction::inverseSymmetry(symmetry)) == action);
      if(action.isPass())
        testAssert(transformed.getActionId() == GameAction::PASS_ACTION_ID);
      else {
        int expectedX = action.getCanvasX();
        int expectedY = action.getCanvasY();
        if((symmetry & 2) != 0)
          expectedX = 18-expectedX;
        if((symmetry & 1) != 0)
          expectedY = 18-expectedY;
        if((symmetry & 4) != 0)
          std::swap(expectedX,expectedY);
        testAssert(transformed.getCanvasX() == expectedX);
        testAssert(transformed.getCanvasY() == expectedY);
      }
      for(int boardSize: {9,13,19}) {
        if(action.isInBoardFootprint(boardSize))
          testAssert(transformed.isInBoardFootprint(boardSize));
      }
    }
  }
  expectGameActionError("invalid-symmetry",[]() { GameAction::pass().transformed(-1); });
  expectGameActionError("invalid-symmetry",[]() { GameAction::pass().transformed(8); });

  json invalidVersion = {{"schemaVersion","action-v2"},{"actionId",0},{"kind","NORMAL"}};
  json mismatchedKind = {{"schemaVersion","action-v1"},{"actionId",0},{"kind","EIGHTWAY"}};
  json extraField = {{"schemaVersion","action-v1"},{"actionId",0},{"kind","NORMAL"},{"canvasX",0}};
  json missingKind = {{"schemaVersion","action-v1"},{"actionId",0}};
  json booleanId = {{"schemaVersion","action-v1"},{"actionId",true},{"kind","NORMAL"}};
  json negativeId = {{"schemaVersion","action-v1"},{"actionId",-1},{"kind","NORMAL"}};
  json tooLargeId = {{"schemaVersion","action-v1"},{"actionId",1445},{"kind","PASS"}};
  for(const json& malformed: {invalidVersion,mismatchedKind,extraField,missingKind,booleanId,negativeId,tooLargeId}) {
    expectGameActionError("schema-validation",[&malformed]() { GameAction::ofJson(malformed); });
  }
}

void runEmbeddedCanonicalizationTests() {
  testAssert(decodeHex("7b7d") == "{}");
  expectStringErrorContaining("Odd-length hex",[]() { decodeHex("0"); });
  expectStringErrorContaining("lowercase",[]() { decodeHex("7B"); });

  const string safeRaw = " { \"max\" : 9007199254740991, \"min\" : -9007199254740991, \"nested\" : { \"b\" : [3,true,false,null], \"a\" : \"text\" } } ";
  const string safeExpected = "{\"max\":9007199254740991,\"min\":-9007199254740991,\"nested\":{\"a\":\"text\",\"b\":[3,true,false,null]}}";
  testAssert(RulesetIdentity::canonicalizeRestrictedJson(safeRaw) == safeExpected);
  testAssert(RulesetIdentity::canonicalizeRestrictedJson("{\"n\":-0}") == "{\"n\":0}");
  testAssert(
    RulesetIdentity::canonicalizeRestrictedJson("{\"slash\":\"\\/\",\"unicodeEscape\":\"\\u0041\",\"controls\":\"\\b\\t\\n\\f\\r\"}") ==
    "{\"controls\":\"\\b\\t\\n\\f\\r\",\"slash\":\"/\",\"unicodeEscape\":\"A\"}"
  );
  string delRaw = "{\"nul\":\"\\u0000\",\"unitSeparator\":\"\\u001f\",\"del\":\"";
  delRaw.push_back(static_cast<char>(0x7F));
  delRaw += "\"}";
  string delExpected = "{\"del\":\"";
  delExpected.push_back(static_cast<char>(0x7F));
  delExpected += "\",\"nul\":\"\\u0000\",\"unitSeparator\":\"\\u001f\"}";
  testAssert(RulesetIdentity::canonicalizeRestrictedJson(delRaw) == delExpected);
  testAssert(RulesetIdentity::sha256Hex("{}") == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a");

  expectRulesetIdentityError("duplicate-key",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1,\"a\":2}"); });
  expectRulesetIdentityError("duplicate-key",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1,\"\\u0061\":2}"); });
  expectRulesetIdentityError("duplicate-key",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"\\u00e9\":1,\"\\u00e9\":2}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1,\"a\":2"); });
  expectRulesetIdentityError("floating-point",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1.0}"); });
  expectRulesetIdentityError("floating-point",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1e0}"); });
  expectRulesetIdentityError("floating-point",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1.0e}"); });
  expectRulesetIdentityError("floating-point",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1.0x}"); });
  expectRulesetIdentityError("unsafe-integer",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":9007199254740992}"); });
  expectRulesetIdentityError("unsafe-integer",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":-9007199254740992}"); });
  expectRulesetIdentityError("unsafe-integer",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":9007199254740992.}"); });
  expectRulesetIdentityError("non-ascii-string",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":\"\\u00e9\"}"); });
  expectRulesetIdentityError("non-ascii-key",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"\\u00e9\":1}"); });
  expectRulesetIdentityError("non-ascii-key",[]() {
    RulesetIdentity::canonicalizeRestrictedJson("{\"a\":\"\\u00e9\",\"\\u00e9\":0}");
  });
  expectRulesetIdentityError("non-ascii-key",[]() {
    RulesetIdentity::canonicalizeRestrictedJson("{\"z\":{\"\\u00e9\":0},\"a\":\"\\u00e9\"}");
  });
  expectRulesetIdentityError("non-ascii-string",[]() {
    RulesetIdentity::canonicalizeRestrictedJson("[\"\\u00e9\",{\"\\u00e9\":0}]");
  });
  expectRulesetIdentityError("non-ascii-string",[]() { RulesetIdentity::parseRestrictedJson("{\"a\":\"\\u00e9\"}"); });
  expectRulesetIdentityError("non-ascii-key",[]() { RulesetIdentity::parseRestrictedJson("{\"\\u00e9\":1}"); });
  expectRulesetIdentityError("non-ascii-string",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":\"\\ud800\"}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":\"\\u00e9\""); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"\\u00e9\":1"); });
  expectRulesetIdentityError("invalid-json-number",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":NaN}"); });
  expectRulesetIdentityError("invalid-json-number",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":NaNx}"); });
  expectRulesetIdentityError("invalid-json-number",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":Infinity}"); });
  expectRulesetIdentityError("invalid-json-number",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":-Infinity}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":nan}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":Nonsense}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":Infinite}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":tru}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":fals}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":nul}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":True}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":nullx}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1.}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1e}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1.e0}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":01}"); });
  expectRulesetIdentityError("invalid-json",[]() { RulesetIdentity::canonicalizeRestrictedJson("{\"a\":1"); });
  string invalidUtf8 = "{\"a\":\"";
  invalidUtf8.push_back(static_cast<char>(0xFF));
  invalidUtf8 += "\"}";
  expectRulesetIdentityError("invalid-utf8",[&invalidUtf8]() { RulesetIdentity::canonicalizeRestrictedJson(invalidUtf8); });

  json floatValue = 1.0;
  expectRulesetIdentityError("floating-point",[&floatValue]() { RulesetIdentity::canonicalizeRestrictedJson(floatValue); });
  json unsafeValue = static_cast<uint64_t>(RulesetIdentity::SAFE_INTEGER_MAX) + 1;
  expectRulesetIdentityError("unsafe-integer",[&unsafeValue]() { RulesetIdentity::canonicalizeRestrictedJson(unsafeValue); });

  string deep;
  for(int i = 0; i < 257; i++)
    deep.push_back('[');
  deep.push_back('0');
  for(int i = 0; i < 257; i++)
    deep.push_back(']');
  testAssert(RulesetIdentity::canonicalizeRestrictedJson(deep) == deep);
}

void runCanonicalizationVectorTests(const string& path) {
  json vectors = RulesetIdentity::parseRestrictedJson(FileUtils::readFileBinary(path));
  requireExactKeys(vectors,{"vectorVersion","profile","validCases","invalidCases"},"Canonicalization vectors");
  testAssert(vectors.at("vectorVersion") == "canonicalization-v1");
  testAssert(vectors.at("profile") == RulesetIdentity::CANONICALIZATION_PROFILE);
  requireCaseIds(
    vectors.at("validCases"),
    {
      "empty-object",
      "ascii-key-order",
      "nested-safe-integers",
      "escape-normalization",
      "negative-zero-integer",
      "top-level-array",
      "control-escapes-and-del",
    },
    "Canonicalization valid vectors"
  );
  requireCaseIds(
    vectors.at("invalidCases"),
    {
      "duplicate-top-level-key",
      "duplicate-nested-key",
      "duplicate-escaped-key-alias",
      "floating-point-decimal",
      "floating-point-exponent",
      "unsafe-positive-integer",
      "unsafe-negative-integer",
      "overlong-positive-integer",
      "non-ascii-string",
      "non-ascii-key",
      "escaped-non-ascii-string",
      "escaped-non-ascii-key",
      "lone-surrogate-string",
      "non-json-number",
      "invalid-utf8",
      "malformed-json",
      "leading-zero-integer",
    },
    "Canonicalization invalid vectors"
  );
  for(const json& vectorCase: vectors.at("validCases")) {
    requireExactKeys(vectorCase,{"id","input","expectedCanonicalUtf8","sha256"},"Canonicalization valid case");
    requireExactKeys(vectorCase.at("input"),{"encoding","data"},"Canonicalization valid input");
    testAssert(vectorCase.at("input").at("encoding") == "UTF-8-HEX");
    string raw = decodeHex(vectorCase.at("input").at("data").get<string>());
    string canonical = RulesetIdentity::canonicalizeRestrictedJson(raw);
    testAssert(canonical == vectorCase.at("expectedCanonicalUtf8").get<string>());
    testAssert(RulesetIdentity::sha256Hex(canonical) == vectorCase.at("sha256").get<string>());
  }
  for(const json& vectorCase: vectors.at("invalidCases")) {
    requireExactKeys(vectorCase,{"id","input","expectedErrorCode"},"Canonicalization invalid case");
    requireExactKeys(vectorCase.at("input"),{"encoding","data"},"Canonicalization invalid input");
    testAssert(vectorCase.at("input").at("encoding") == "UTF-8-HEX");
    string raw = decodeHex(vectorCase.at("input").at("data").get<string>());
    string expectedCode = vectorCase.at("expectedErrorCode").get<string>();
    expectRulesetIdentityError(expectedCode,[&raw]() { RulesetIdentity::canonicalizeRestrictedJson(raw); });
  }
}

void runActionSchemaTests(const string& path) {
  json schema = RulesetIdentity::parseRestrictedJson(FileUtils::readFileBinary(path));
  requireExactKeys(schema,{"$schema","$id","title","description","oneOf"},"Action Schema V1 root");
  testAssert(schema.at("$schema") == "https://json-schema.org/draft/2020-12/schema");
  testAssert(schema.at("$id") == "action-v1.schema.json");
  testAssert(schema.at("oneOf").is_array());
  testAssert(schema.at("oneOf").size() == 5);
  testAssert(
    RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(schema)) ==
    GameAction::ACTION_SCHEMA_SHA256
  );

  const string expectedKinds[5] = {"NORMAL","IMMORTAL","DOUBLE_START","EIGHTWAY","PASS"};
  const int expectedFirst[5] = {0,361,722,1083,1444};
  const int expectedLast[5] = {360,721,1082,1443,1444};
  for(int i = 0; i < 5; i++) {
    const json& branch = schema.at("oneOf").at(i);
    requireExactKeys(branch,{"type","additionalProperties","required","properties"},"Action Schema V1 branch");
    testAssert(branch.at("type") == "object");
    testAssert(branch.at("additionalProperties") == false);
    testAssert(branch.at("required") == json({"schemaVersion","actionId","kind"}));
    const json& properties = branch.at("properties");
    requireExactKeys(properties,{"schemaVersion","actionId","kind"},"Action Schema V1 branch properties");
    testAssert(properties.at("schemaVersion").at("const") == "action-v1");
    testAssert(properties.at("kind").at("const") == expectedKinds[i]);
    if(i < 4) {
      testAssert(properties.at("actionId").at("type") == "integer");
      testAssert(properties.at("actionId").at("minimum") == expectedFirst[i]);
      testAssert(properties.at("actionId").at("maximum") == expectedLast[i]);
    }
    else
      testAssert(properties.at("actionId").at("const") == GameAction::PASS_ACTION_ID);
  }
}

void runActionVectorTests(const string& path) {
  json vectors = RulesetIdentity::parseRestrictedJson(FileUtils::readFileBinary(path));
  requireExactKeys(
    vectors,
    {
      "vectorVersion",
      "constants",
      "exhaustiveCodec",
      "familyBoundaries",
      "centeredMappings",
      "exhaustiveCenteredMappings",
      "exhaustiveBoardFootprints",
      "offBoardRejections",
      "invalidEnvelopes",
      "d4RoundTrips",
      "exhaustiveD4",
    },
    "Action vectors"
  );
  testAssert(vectors.at("vectorVersion") == "action-v1");
  requireCaseIds(
    vectors.at("centeredMappings"),
    {
      "n9-top-left","n9-asymmetric","n9-center","n9-bottom-right",
      "n13-top-left","n13-asymmetric","n13-center","n13-bottom-right",
      "n19-top-left","n19-asymmetric","n19-center","n19-bottom-right",
    },
    "Centered action mappings"
  );
  requireCaseIds(vectors.at("offBoardRejections"),expectedOffBoardCaseIds(),"Off-board action rejections");
  requireCaseIds(
    vectors.at("invalidEnvelopes"),
    {
      "unknown-schema-version",
      "action-id-kind-mismatch",
      "redundant-coordinate-field",
      "missing-schema-version",
      "missing-action-id",
      "missing-kind",
      "unknown-envelope-kind",
    },
    "Invalid action envelopes"
  );
  requireCaseIds(vectors.at("d4RoundTrips"),expectedD4CaseIds(),"D4 action round trips");
  const json& constants = vectors.at("constants");
  requireExactKeys(
    constants,
    {
      "canvasSize",
      "canvasPointCount",
      "kindStride",
      "flatActionCount",
      "passActionId",
      "boardOffsets",
      "semanticPointEncoding",
      "inverseSymmetryIds",
    },
    "Action vector constants"
  );
  requireExactKeys(constants.at("boardOffsets"),{"9","13","19"},"Action vector board offsets");
  testAssert(constants.at("boardOffsets").at("9") == 5);
  testAssert(constants.at("boardOffsets").at("13") == 3);
  testAssert(constants.at("boardOffsets").at("19") == 0);
  testAssert(constants.at("semanticPointEncoding") == "BOARD_LOCAL_ROW_MAJOR");
  testAssert(constants.at("canvasSize") == GameAction::CANVAS_SIZE);
  testAssert(constants.at("canvasPointCount") == GameAction::CANVAS_POINT_COUNT);
  testAssert(constants.at("kindStride") == GameAction::KIND_STRIDE);
  testAssert(constants.at("flatActionCount") == GameAction::FLAT_ACTION_COUNT);
  testAssert(constants.at("passActionId") == GameAction::PASS_ACTION_ID);
  json inverseSymmetryIds = json::array();
  for(int symmetry = 0; symmetry < GameAction::SYMMETRY_COUNT; symmetry++)
    inverseSymmetryIds.push_back(GameAction::inverseSymmetry(symmetry));
  testAssert(constants.at("inverseSymmetryIds") == inverseSymmetryIds);

  const string expectedFamilyKinds[5] = {"NORMAL","IMMORTAL","DOUBLE_START","EIGHTWAY","PASS"};
  const int expectedFamilyFirst[5] = {0,361,722,1083,1444};
  const int expectedFamilyLast[5] = {360,721,1082,1443,1444};
  testAssert(vectors.at("familyBoundaries").size() == 5);
  for(int i = 0; i < 5; i++) {
    const json& boundary = vectors.at("familyBoundaries").at(i);
    requireExactKeys(boundary,{"kind","kindCode","first","last"},"Action family boundary");
    testAssert(boundary.at("kind") == expectedFamilyKinds[i]);
    if(i < 4)
      testAssert(requireExactIntInRange(boundary.at("kindCode"),0,3,"Action family kindCode") == i);
    else
      testAssert(boundary.at("kindCode").is_null());
    GameAction first = GameAction::ofJson(boundary.at("first"));
    GameAction last = GameAction::ofJson(boundary.at("last"));
    testAssert(first.getActionId() == expectedFamilyFirst[i]);
    testAssert(last.getActionId() == expectedFamilyLast[i]);
    testAssert(GameAction::kindToString(first.getKind()) == expectedFamilyKinds[i]);
    testAssert(GameAction::kindToString(last.getKind()) == expectedFamilyKinds[i]);
  }

  for(const json& mapping: vectors.at("centeredMappings")) {
    requireExactKeys(
      mapping,
      {"id","boardSize","semanticX","semanticY","semanticPointIndex","canvasX","canvasY","canvasPointIndex","actionIds"},
      "Centered action mapping"
    );
    requireExactKeys(mapping.at("actionIds"),{"NORMAL","IMMORTAL","DOUBLE_START","EIGHTWAY"},"Centered action IDs");
    int boardSize = requireSupportedBoardSize(mapping.at("boardSize"),"Centered action boardSize");
    int x = requireExactIntInRange(mapping.at("semanticX"),0,boardSize-1,"Centered action semanticX");
    int y = requireExactIntInRange(mapping.at("semanticY"),0,boardSize-1,"Centered action semanticY");
    int semanticPointIndex = requireExactIntInRange(
      mapping.at("semanticPointIndex"),0,boardSize*boardSize-1,"Centered action semanticPointIndex"
    );
    int canvasX = requireExactIntInRange(
      mapping.at("canvasX"),0,GameAction::CANVAS_SIZE-1,"Centered action canvasX"
    );
    int canvasY = requireExactIntInRange(
      mapping.at("canvasY"),0,GameAction::CANVAS_SIZE-1,"Centered action canvasY"
    );
    int canvasPointIndex = requireExactIntInRange(
      mapping.at("canvasPointIndex"),0,GameAction::CANVAS_POINT_COUNT-1,"Centered action canvasPointIndex"
    );
    testAssert(semanticPointIndex == boardSize*y+x);
    testAssert(canvasPointIndex == GameAction::CANVAS_SIZE*canvasY+canvasX);
    for(auto iter = mapping.at("actionIds").begin(); iter != mapping.at("actionIds").end(); ++iter) {
      GameAction action = GameAction::fromBoard(GameAction::parseKind(iter.key()),boardSize,x,y);
      int expectedActionId = requireExactIntInRange(
        iter.value(),0,GameAction::PASS_ACTION_ID-1,"Centered action actionId"
      );
      testAssert(action.getActionId() == expectedActionId);
      testAssert(action.getCanvasX() == canvasX);
      testAssert(action.getCanvasY() == canvasY);
    }
  }

  for(const json& rejection: vectors.at("offBoardRejections")) {
    string operation = rejection.at("operation").get<string>();
    if(operation == "ENCODE_SEMANTIC")
      requireExactKeys(rejection,{"id","operation","boardSize","kind","x","y","expectedErrorCode"},"ENCODE_SEMANTIC rejection");
    else if(operation == "ENCODE_CANVAS")
      requireExactKeys(rejection,{"id","operation","kind","x","y","expectedErrorCode"},"ENCODE_CANVAS rejection");
    else if(operation == "DECODE")
      requireExactKeys(rejection,{"id","operation","actionId","expectedErrorCode"},"DECODE rejection");
    else if(operation == "DECODE_FOR_BOARD")
      requireExactKeys(rejection,{"id","operation","boardSize","actionId","expectedErrorCode"},"DECODE_FOR_BOARD rejection");
    else
      throw StringError("Unknown off-board vector operation: " + operation);
    string expectedCode = rejection.at("expectedErrorCode").get<string>();
    expectGameActionError(expectedCode,[&rejection,&operation]() {
      if(operation == "ENCODE_SEMANTIC") {
        GameAction::fromBoard(
          rejection.at("kind"),
          rejection.at("boardSize"),
          rejection.at("x"),
          rejection.at("y")
        );
      }
      else if(operation == "ENCODE_CANVAS")
        GameAction::fromCanvas(rejection.at("kind"),rejection.at("x"),rejection.at("y"));
      else if(operation == "DECODE")
        GameAction::decode(rejection.at("actionId"));
      else if(operation == "DECODE_FOR_BOARD")
        GameAction::decodeForBoard(rejection.at("actionId"),rejection.at("boardSize"));
      else
        throw StringError("Unknown off-board vector operation: " + operation);
    });
  }

  for(const json& malformed: vectors.at("invalidEnvelopes")) {
    requireExactKeys(malformed,{"id","action","expectedErrorCode"},"Invalid action envelope vector");
    string expectedCode = malformed.at("expectedErrorCode").get<string>();
    const json action = malformed.at("action");
    expectGameActionError(expectedCode,[&action]() { GameAction::ofJson(action); });
  }

  for(const json& roundTrip: vectors.at("d4RoundTrips")) {
    requireExactKeys(
      roundTrip,
      {"id","boardSize","symmetryId","inverseSymmetryId","inputAction","expectedAction","expectedSemanticX","expectedSemanticY"},
      "D4 action round trip"
    );
    GameAction input = GameAction::ofJson(roundTrip.at("inputAction"));
    GameAction expected = GameAction::ofJson(roundTrip.at("expectedAction"));
    int symmetry = requireExactIntInRange(roundTrip.at("symmetryId"),0,7,"D4 symmetryId");
    int inverse = requireExactIntInRange(roundTrip.at("inverseSymmetryId"),0,7,"D4 inverseSymmetryId");
    testAssert(inverse == GameAction::inverseSymmetry(symmetry));
    GameAction transformed = input.transformed(symmetry);
    testAssert(transformed == expected);
    testAssert(transformed.transformed(inverse) == input);
    int boardSize = requireSupportedBoardSize(roundTrip.at("boardSize"),"D4 boardSize");
    if(expected.isPass()) {
      testAssert(roundTrip.at("expectedSemanticX").is_null());
      testAssert(roundTrip.at("expectedSemanticY").is_null());
    }
    else {
      int expectedX = requireExactIntInRange(
        roundTrip.at("expectedSemanticX"),0,boardSize-1,"D4 expectedSemanticX"
      );
      int expectedY = requireExactIntInRange(
        roundTrip.at("expectedSemanticY"),0,boardSize-1,"D4 expectedSemanticY"
      );
      testAssert(expected.getBoardX(boardSize) == expectedX);
      testAssert(expected.getBoardY(boardSize) == expectedY);
    }
  }

  const json& exhaustiveCodec = vectors.at("exhaustiveCodec");
  requireExactKeys(
    exhaustiveCodec,
    {"recordCount","recordOrder","recordFields","canonicalRecordsSha256"},
    "Exhaustive action codec summary"
  );
  testAssert(exhaustiveCodec.at("recordOrder") == "ACTION_ID_ASCENDING");
  testAssert(exhaustiveCodec.at("recordFields") == json({"actionId","kind","canvasX","canvasY"}));
  json codecRecords = actionCodecRecords();
  testAssert(codecRecords.size() == exhaustiveCodec.at("recordCount"));
  testAssert(
    RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(codecRecords)) ==
    exhaustiveCodec.at("canonicalRecordsSha256")
  );

  const json& exhaustiveCentered = vectors.at("exhaustiveCenteredMappings");
  requireExactKeys(
    exhaustiveCentered,
    {"recordOrder","recordFields","perBoard"},
    "Exhaustive centered mappings summary"
  );
  testAssert(exhaustiveCentered.at("recordOrder") == "SEMANTIC_ROW_MAJOR");
  testAssert(
    exhaustiveCentered.at("recordFields") ==
    json({"semanticX","semanticY","semanticPointIndex","canvasX","canvasY","canvasPointIndex","actionIds"})
  );
  const json& centered = exhaustiveCentered.at("perBoard");
  requireExactKeys(centered,{"9","13","19"},"Exhaustive centered mappings perBoard");

  const json& exhaustiveFootprints = vectors.at("exhaustiveBoardFootprints");
  requireExactKeys(
    exhaustiveFootprints,
    {"inputOrder","acceptedRecordFields","rejectedRecordFields","perBoard"},
    "Exhaustive board footprints summary"
  );
  testAssert(exhaustiveFootprints.at("inputOrder") == "ACTION_ID_ASCENDING");
  testAssert(
    exhaustiveFootprints.at("acceptedRecordFields") == json({"actionId","kind","semanticX","semanticY"})
  );
  testAssert(
    exhaustiveFootprints.at("rejectedRecordFields") == json({"actionId","kind","expectedErrorCode"})
  );
  const json& footprints = exhaustiveFootprints.at("perBoard");
  requireExactKeys(footprints,{"9","13","19"},"Exhaustive board footprints perBoard");

  for(int boardSize: {9,13,19}) {
    string key = Global::intToString(boardSize);
    requireExactKeys(
      centered.at(key),
      {"recordCount","canonicalRecordsSha256"},
      "Exhaustive centered mapping board summary"
    );
    json centeredRecords = centeredMappingRecords(boardSize);
    testAssert(centeredRecords.size() == centered.at(key).at("recordCount"));
    testAssert(
      RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(centeredRecords)) ==
      centered.at(key).at("canonicalRecordsSha256")
    );

    requireExactKeys(
      footprints.at(key),
      {
        "acceptedRecordCount",
        "acceptedCanonicalRecordsSha256",
        "rejectedRecordCount",
        "rejectedCanonicalRecordsSha256",
      },
      "Exhaustive board footprint summary"
    );
    json accepted;
    json rejected;
    boardFootprintRecords(boardSize,accepted,rejected);
    testAssert(accepted.size() == footprints.at(key).at("acceptedRecordCount"));
    testAssert(rejected.size() == footprints.at(key).at("rejectedRecordCount"));
    testAssert(
      RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(accepted)) ==
      footprints.at(key).at("acceptedCanonicalRecordsSha256")
    );
    testAssert(
      RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(rejected)) ==
      footprints.at(key).at("rejectedCanonicalRecordsSha256")
    );
  }

  const json& exhaustiveD4 = vectors.at("exhaustiveD4");
  requireExactKeys(
    exhaustiveD4,
    {"recordCountPerSymmetry","inputOrder","output","perSymmetryCanonicalArraySha256"},
    "Exhaustive D4 summary"
  );
  testAssert(exhaustiveD4.at("recordCountPerSymmetry") == GameAction::FLAT_ACTION_COUNT);
  testAssert(exhaustiveD4.at("inputOrder") == "ACTION_ID_ASCENDING");
  testAssert(exhaustiveD4.at("output") == "TRANSFORMED_ACTION_ID_ARRAY");
  const json& d4Digests = exhaustiveD4.at("perSymmetryCanonicalArraySha256");
  requireExactKeys(d4Digests,{"0","1","2","3","4","5","6","7"},"Exhaustive D4 digests");
  for(int symmetry = 0; symmetry < GameAction::SYMMETRY_COUNT; symmetry++) {
    json transformedIds = json::array();
    for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++)
      transformedIds.push_back(GameAction::decode(actionId).transformed(symmetry).getActionId());
    string key = Global::intToString(symmetry);
    testAssert(
      RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(transformedIds)) ==
      d4Digests.at(key)
    );
  }
}

void runDescriptorVectorTests(
  const string& descriptorPath,
  const string& schemaPath,
  const string& publicIdentityPath,
  const string& invalidDescriptorPath
) {
  string descriptorRaw = FileUtils::readFileBinary(descriptorPath);
  string schemaRaw = FileUtils::readFileBinary(schemaPath);
  testAssert(
    RulesetIdentity::sha256Hex(RulesetIdentity::canonicalizeRestrictedJson(schemaRaw)) ==
    RulesetIdentity::DESCRIPTOR_SCHEMA_SHA256
  );
  RulesetIdentity identity = RulesetIdentity::fromDescriptorJson(descriptorRaw,schemaRaw,true);
  testAssert(identity.getRulesetId() == RulesetIdentity::PUBLIC_RULESET_ID);
  testAssert(identity.getSemanticVersion() == RulesetIdentity::PUBLIC_SEMANTIC_VERSION);
  testAssert(identity.getDescriptorSha256() == RulesetIdentity::PUBLIC_DESCRIPTOR_SHA256);
  testAssert(identity.toJson().at("descriptorSha256") == RulesetIdentity::PUBLIC_DESCRIPTOR_SHA256);

  json publicVector = RulesetIdentity::parseRestrictedJson(FileUtils::readFileBinary(publicIdentityPath));
  requireExactKeys(
    publicVector,
    {"vectorVersion","descriptorFile","canonicalizationProfile","canonicalUtf8ByteLength","publicIdentity"},
    "Public identity vector"
  );
  requireExactKeys(publicVector.at("publicIdentity"),{"rulesetId","semanticVersion","descriptorSha256"},"Public identity");
  testAssert(publicVector.at("vectorVersion") == "public-identity-v1");
  testAssert(publicVector.at("descriptorFile") == "../descriptor-v0.1.0-draft.json");
  testAssert(publicVector.at("canonicalizationProfile") == RulesetIdentity::CANONICALIZATION_PROFILE);
  testAssert(publicVector.at("canonicalUtf8ByteLength") == identity.getCanonicalDescriptorBytes().size());
  testAssert(publicVector.at("publicIdentity") == identity.toJson());

  json invalidVectors = RulesetIdentity::parseRestrictedJson(FileUtils::readFileBinary(invalidDescriptorPath));
  requireExactKeys(invalidVectors,{"vectorVersion","baseDescriptor","cases"},"Invalid descriptor vectors");
  testAssert(invalidVectors.at("vectorVersion") == "descriptor-invalid-v1");
  testAssert(invalidVectors.at("baseDescriptor") == "../descriptor-v0.1.0-draft.json");
  requireCaseIds(
    invalidVectors.at("cases"),
    {
      "unknown-top-level-field",
      "unknown-nested-field",
      "missing-public-ruleset-id",
      "repository-slug-is-not-public-id",
      "initial-psk-seed-must-be-true",
      "initial-state-psk-seed-must-be-true",
      "point-major-layout-rejected",
      "dead-stone-shortcut-is-deferred",
      "digest-encoding-must-be-lowercase",
      "semantic-version-is-frozen",
      "official-version-semantic-drift-rejected-nonpublic",
    },
    "Invalid descriptor vectors"
  );
  json baseDescriptor = RulesetIdentity::parseRestrictedJson(descriptorRaw);
  for(const json& vectorCase: invalidVectors.at("cases")) {
    string operation = vectorCase.at("operation").get<string>();
    bool hasRequirePublic = vectorCase.find("requirePublic") != vectorCase.end();
    if(operation == "REMOVE") {
      if(hasRequirePublic)
        requireExactKeys(vectorCase,{"id","operation","jsonPointer","requirePublic","expectedErrorCode"},"Invalid descriptor REMOVE case");
      else
        requireExactKeys(vectorCase,{"id","operation","jsonPointer","expectedErrorCode"},"Invalid descriptor REMOVE case");
    }
    else {
      if(hasRequirePublic)
        requireExactKeys(vectorCase,{"id","operation","jsonPointer","value","requirePublic","expectedErrorCode"},"Invalid descriptor mutation case");
      else
        requireExactKeys(vectorCase,{"id","operation","jsonPointer","value","expectedErrorCode"},"Invalid descriptor mutation case");
    }
    bool requirePublic = true;
    if(hasRequirePublic) {
      testAssert(vectorCase.at("requirePublic").is_boolean());
      requirePublic = vectorCase.at("requirePublic").get<bool>();
    }
    json mutated = mutateDescriptor(baseDescriptor,vectorCase);
    string mutatedRaw = RulesetIdentity::canonicalizeRestrictedJson(mutated);
    string expectedCode = vectorCase.at("expectedErrorCode").get<string>();
    expectRulesetIdentityError(expectedCode,[&mutatedRaw,&schemaRaw,requirePublic]() {
      RulesetIdentity::fromDescriptorJson(mutatedRaw,schemaRaw,requirePublic);
    });
  }

  json substitutedSchema = {
    {"$schema","https://json-schema.org/draft/2020-12/schema"},
    {"$id",RulesetIdentity::DESCRIPTOR_SCHEMA_ID},
  };
  string substitutedSchemaRaw = RulesetIdentity::canonicalizeRestrictedJson(substitutedSchema);
  expectRulesetIdentityError("schema-validation",[&descriptorRaw,&substitutedSchemaRaw]() {
    RulesetIdentity::fromDescriptorJson(descriptorRaw,substitutedSchemaRaw,false);
  });

  json reusedOfficialVersion = baseDescriptor;
  reusedOfficialVersion["initialState"]["boardSize"] = 9;
  reusedOfficialVersion["boardPolicy"]["selectedBoardSize"] = 9;
  string reusedOfficialVersionRaw = RulesetIdentity::canonicalizeRestrictedJson(reusedOfficialVersion);
  expectRulesetIdentityError("descriptor-validation",[&reusedOfficialVersionRaw,&schemaRaw]() {
    RulesetIdentity::fromDescriptorJson(reusedOfficialVersionRaw,schemaRaw,false);
  });

  json experimental = reusedOfficialVersion;
  experimental["identity"]["semanticVersion"] = "0.1.0-draft-n9-qtest";
  experimental["quotas"]["initialByPlayer"]["BLACK"]["IMMORTAL"] = 0;
  RulesetIdentity candidate = RulesetIdentity::fromDescriptorJson(
    RulesetIdentity::canonicalizeRestrictedJson(experimental),schemaRaw,false
  );
  testAssert(candidate.getRulesetId() == RulesetIdentity::PUBLIC_RULESET_ID);
  testAssert(candidate.getSemanticVersion() == "0.1.0-draft-n9-qtest");
  testAssert(candidate.getDescriptorSha256() != RulesetIdentity::PUBLIC_DESCRIPTOR_SHA256);
}

}

void Tests::runCollapseContractTests() {
  cout << "Running Collapse Go executable contract tests" << endl;

  runMandatoryArtifactFailureTests();
  map<string,string> artifacts = requireContractArtifacts(findRepoFile);
  requireExactContractArtifactSets(artifacts);

  runEmbeddedGameActionTests();
  runEmbeddedCanonicalizationTests();
  runCanonicalizationVectorTests(
    artifacts.at("rulesets/collapse-go/vectors/canonicalization-v1.json")
  );
  runActionSchemaTests(
    artifacts.at("schemas/source/action-v1.schema.json")
  );
  runActionVectorTests(
    artifacts.at("rulesets/collapse-go/vectors/action-v1.json")
  );
  runDescriptorVectorTests(
    artifacts.at("rulesets/collapse-go/descriptor-v0.1.0-draft.json"),
    artifacts.at("schemas/source/ruleset-descriptor-v1.schema.json"),
    artifacts.at("rulesets/collapse-go/vectors/public-identity-v1.json"),
    artifacts.at("rulesets/collapse-go/vectors/descriptor-invalid-v1.json")
  );
}
