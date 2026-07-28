#include "../game/gameaction.h"

#include <limits>

using nlohmann::json;
using namespace std;

const string GameAction::ACTION_SCHEMA_SHA256 = "6fa4de4f57366ef14ed24a95c6c578576591ed49c2f9fcd0fe8d244921e6df63";

GameActionError::GameActionError(const string& errorCode, const string& errorMessage)
  : StringError(errorMessage), code(errorCode)
{}

const string& GameActionError::getCode() const {
  return code;
}

GameAction::GameAction(GameActionKind actionKind, int actionCanvasX, int actionCanvasY)
  : kind(actionKind), canvasX(actionCanvasX), canvasY(actionCanvasY)
{}

GameAction GameAction::pass() {
  return GameAction(GameActionKind::PASS,-1,-1);
}

void GameAction::requireCanvasPoint(int x, int y) {
  if(x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE)
    throw GameActionError("point-off-board","Action point is outside the 19x19 action canvas");
}

bool GameAction::isPointKind(GameActionKind actionKind) {
  return actionKind == GameActionKind::NORMAL ||
    actionKind == GameActionKind::IMMORTAL ||
    actionKind == GameActionKind::DOUBLE_START ||
    actionKind == GameActionKind::EIGHTWAY;
}

int GameAction::kindCode(GameActionKind actionKind) {
  switch(actionKind) {
  case GameActionKind::NORMAL: return 0;
  case GameActionKind::IMMORTAL: return 1;
  case GameActionKind::DOUBLE_START: return 2;
  case GameActionKind::EIGHTWAY: return 3;
  case GameActionKind::PASS:
    throw GameActionError("unknown-action-kind","PASS has no point-action kind code");
  default:
    throw GameActionError("unknown-action-kind","Unknown action kind");
  }
}

string GameAction::kindToString(GameActionKind actionKind) {
  switch(actionKind) {
  case GameActionKind::NORMAL: return "NORMAL";
  case GameActionKind::IMMORTAL: return "IMMORTAL";
  case GameActionKind::DOUBLE_START: return "DOUBLE_START";
  case GameActionKind::EIGHTWAY: return "EIGHTWAY";
  case GameActionKind::PASS: return "PASS";
  default:
    throw GameActionError("unknown-action-kind","Unknown action kind");
  }
}

GameActionKind GameAction::parseKind(const string& name) {
  if(name == "NORMAL")
    return GameActionKind::NORMAL;
  if(name == "IMMORTAL")
    return GameActionKind::IMMORTAL;
  if(name == "DOUBLE_START")
    return GameActionKind::DOUBLE_START;
  if(name == "EIGHTWAY")
    return GameActionKind::EIGHTWAY;
  if(name == "PASS")
    return GameActionKind::PASS;
  throw GameActionError("unknown-action-kind","Unknown action kind: " + name);
}

GameAction GameAction::fromCanvas(GameActionKind actionKind, int x, int y) {
  if(!isPointKind(actionKind))
    throw GameActionError("non-canonical-action","PASS cannot carry point coordinates");
  requireCanvasPoint(x,y);
  return GameAction(actionKind,x,y);
}

int64_t GameAction::requireJsonInteger(const json& value, const string& fieldName) {
  static constexpr int64_t safeIntegerMinimum = -9007199254740991LL;
  static constexpr int64_t safeIntegerMaximum = 9007199254740991LL;
  if(value.is_number_unsigned()) {
    uint64_t unsignedValue = value.get<uint64_t>();
    if(unsignedValue > static_cast<uint64_t>(safeIntegerMaximum))
      throw GameActionError("unsafe-integer",fieldName + " is outside the safe signed integer range");
    return static_cast<int64_t>(unsignedValue);
  }
  if(value.is_number_integer()) {
    int64_t signedValue = value.get<int64_t>();
    if(signedValue < safeIntegerMinimum || signedValue > safeIntegerMaximum)
      throw GameActionError("unsafe-integer",fieldName + " is outside the safe signed integer range");
    return signedValue;
  }
  throw GameActionError("invalid-integer",fieldName + " must be an integer");
}

GameActionKind GameAction::requireJsonKind(const json& value) {
  if(!value.is_string())
    throw GameActionError("unknown-action-kind","Action kind must be a string");
  return parseKind(value.get<string>());
}

GameAction GameAction::fromCanvas(const json& actionKind, const json& x, const json& y) {
  GameActionKind parsedKind = requireJsonKind(actionKind);
  if(!isPointKind(parsedKind))
    throw GameActionError("unknown-action-kind","PASS is not a point action kind");
  int64_t parsedX = requireJsonInteger(x,"canvasX");
  int64_t parsedY = requireJsonInteger(y,"canvasY");
  if(parsedX < 0 || parsedX >= CANVAS_SIZE || parsedY < 0 || parsedY >= CANVAS_SIZE)
    throw GameActionError("point-off-board","Action point is outside the 19x19 action canvas");
  return fromCanvas(parsedKind,static_cast<int>(parsedX),static_cast<int>(parsedY));
}

bool GameAction::isSupportedBoardSize(int boardSize) {
  return boardSize == 9 || boardSize == 13 || boardSize == 19;
}

int GameAction::boardOffset(int boardSize) {
  if(!isSupportedBoardSize(boardSize))
    throw GameActionError("unsupported-board-size","Only centered 9x9, 13x13, and 19x19 boards are supported");
  return (CANVAS_SIZE - boardSize) / 2;
}

GameAction GameAction::fromBoard(GameActionKind actionKind, int boardSize, int x, int y) {
  int offset = boardOffset(boardSize);
  if(x < 0 || x >= boardSize || y < 0 || y >= boardSize)
    throw GameActionError("point-off-board","Action point is outside the semantic board");
  return fromCanvas(actionKind,x+offset,y+offset);
}

GameAction GameAction::fromBoard(const json& actionKind, const json& boardSize, const json& x, const json& y) {
  int64_t parsedBoardSize = requireJsonInteger(boardSize,"boardSize");
  if(parsedBoardSize != 9 && parsedBoardSize != 13 && parsedBoardSize != 19)
    throw GameActionError("unsupported-board-size","Only centered 9x9, 13x13, and 19x19 boards are supported");
  int boardSizeInt = static_cast<int>(parsedBoardSize);
  int64_t parsedX = requireJsonInteger(x,"semanticX");
  int64_t parsedY = requireJsonInteger(y,"semanticY");
  if(parsedX < 0 || parsedX >= boardSizeInt || parsedY < 0 || parsedY >= boardSizeInt)
    throw GameActionError("point-off-board","Action point is outside the semantic board");
  GameActionKind parsedKind = requireJsonKind(actionKind);
  if(!isPointKind(parsedKind))
    throw GameActionError("unknown-action-kind","PASS is not a point action kind");
  return fromBoard(
    parsedKind,
    boardSizeInt,
    static_cast<int>(parsedX),
    static_cast<int>(parsedY)
  );
}

GameAction GameAction::decode(int actionId) {
  if(actionId < 0 || actionId >= FLAT_ACTION_COUNT)
    throw GameActionError("action-id-out-of-range","Action ID is outside 0..1444");
  if(actionId == PASS_ACTION_ID)
    return pass();

  int code = actionId / KIND_STRIDE;
  int point = actionId % KIND_STRIDE;
  int x = point % CANVAS_SIZE;
  int y = point / CANVAS_SIZE;
  GameActionKind actionKind;
  switch(code) {
  case 0: actionKind = GameActionKind::NORMAL; break;
  case 1: actionKind = GameActionKind::IMMORTAL; break;
  case 2: actionKind = GameActionKind::DOUBLE_START; break;
  case 3: actionKind = GameActionKind::EIGHTWAY; break;
  default:
    throw GameActionError("action-id-out-of-range","Action ID has an unknown point-action block");
  }
  return GameAction(actionKind,x,y);
}

GameAction GameAction::decode(const json& actionId) {
  int64_t parsedActionId = requireJsonInteger(actionId,"actionId");
  if(parsedActionId < 0 || parsedActionId >= FLAT_ACTION_COUNT)
    throw GameActionError("action-id-out-of-range","Action ID is outside 0..1444");
  return decode(static_cast<int>(parsedActionId));
}

GameAction GameAction::decodeForBoard(int actionId, int boardSize) {
  GameAction action = decode(actionId);
  if(!action.isInBoardFootprint(boardSize))
    throw GameActionError("point-off-board","Action lies outside the centered board footprint");
  return action;
}

GameAction GameAction::decodeForBoard(const json& actionId, const json& boardSize) {
  int64_t parsedBoardSize = requireJsonInteger(boardSize,"boardSize");
  if(parsedBoardSize != 9 && parsedBoardSize != 13 && parsedBoardSize != 19)
    throw GameActionError("unsupported-board-size","Only centered 9x9, 13x13, and 19x19 boards are supported");
  int64_t parsedActionId = requireJsonInteger(actionId,"actionId");
  if(parsedActionId < 0 || parsedActionId >= FLAT_ACTION_COUNT)
    throw GameActionError("action-id-out-of-range","Action ID is outside 0..1444");
  return decodeForBoard(static_cast<int>(parsedActionId),static_cast<int>(parsedBoardSize));
}

GameActionKind GameAction::getKind() const {
  return kind;
}

int GameAction::getCanvasX() const {
  return canvasX;
}

int GameAction::getCanvasY() const {
  return canvasY;
}

int GameAction::getActionId() const {
  if(isPass())
    return PASS_ACTION_ID;
  return KIND_STRIDE * kindCode(kind) + CANVAS_SIZE * canvasY + canvasX;
}

bool GameAction::isPass() const {
  return kind == GameActionKind::PASS;
}

bool GameAction::isInBoardFootprint(int boardSize) const {
  int offset = boardOffset(boardSize);
  if(isPass())
    return true;
  return canvasX >= offset && canvasX < offset + boardSize &&
    canvasY >= offset && canvasY < offset + boardSize;
}

int GameAction::getBoardX(int boardSize) const {
  int offset = boardOffset(boardSize);
  if(isPass())
    return -1;
  if(!isInBoardFootprint(boardSize))
    throw GameActionError("point-off-board","Action lies outside the centered board footprint");
  return canvasX - offset;
}

int GameAction::getBoardY(int boardSize) const {
  int offset = boardOffset(boardSize);
  if(isPass())
    return -1;
  if(!isInBoardFootprint(boardSize))
    throw GameActionError("point-off-board","Action lies outside the centered board footprint");
  return canvasY - offset;
}

void GameAction::requireSymmetry(int symmetryId) {
  if(symmetryId < 0 || symmetryId >= SYMMETRY_COUNT)
    throw GameActionError("invalid-symmetry","Symmetry ID is outside 0..7");
}

int GameAction::inverseSymmetry(int symmetryId) {
  requireSymmetry(symmetryId);
  static const int inverseIds[SYMMETRY_COUNT] = {0,1,2,3,4,6,5,7};
  return inverseIds[symmetryId];
}

GameAction GameAction::transformed(int symmetryId) const {
  requireSymmetry(symmetryId);
  if(isPass())
    return pass();

  int x = canvasX;
  int y = canvasY;
  if((symmetryId & 2) != 0)
    x = CANVAS_SIZE-1-x;
  if((symmetryId & 1) != 0)
    y = CANVAS_SIZE-1-y;
  if((symmetryId & 4) != 0)
    std::swap(x,y);
  return fromCanvas(kind,x,y);
}

json GameAction::toJson() const {
  json value;
  value["schemaVersion"] = "action-v1";
  value["actionId"] = getActionId();
  value["kind"] = kindToString(kind);
  return value;
}

GameAction GameAction::ofJson(const json& value) {
  try {
    if(!value.is_object() || value.size() != 3 ||
       value.find("schemaVersion") == value.end() ||
       value.find("actionId") == value.end() ||
       value.find("kind") == value.end())
      throw GameActionError("schema-validation","Action envelope must contain exactly schemaVersion, actionId, and kind");

    const json& schemaVersion = value.at("schemaVersion");
    const json& actionIdValue = value.at("actionId");
    const json& kindValue = value.at("kind");
    if(!schemaVersion.is_string() || schemaVersion.get<string>() != "action-v1")
      throw GameActionError("schema-validation","Action schemaVersion must be action-v1");
    if(!kindValue.is_string())
      throw GameActionError("schema-validation","Action kind must be a string");

    int actionId;
    if(actionIdValue.is_number_unsigned()) {
      uint64_t unsignedValue = actionIdValue.get<uint64_t>();
      if(unsignedValue > static_cast<uint64_t>(numeric_limits<int>::max()))
        throw GameActionError("schema-validation","Action ID is outside the integer range");
      actionId = static_cast<int>(unsignedValue);
    }
    else if(actionIdValue.is_number_integer()) {
      int64_t signedValue = actionIdValue.get<int64_t>();
      if(signedValue < numeric_limits<int>::min() || signedValue > numeric_limits<int>::max())
        throw GameActionError("schema-validation","Action ID is outside the integer range");
      actionId = static_cast<int>(signedValue);
    }
    else
      throw GameActionError("schema-validation","Action ID must be an integer");

    GameAction expected = pass();
    try {
      expected = decode(actionId);
    }
    catch(const GameActionError&) {
      throw GameActionError("schema-validation","Action ID is outside the Action Schema V1 range");
    }
    if(kindValue.get<string>() != kindToString(expected.kind))
      throw GameActionError("schema-validation","Action kind does not match its kind-major action ID");
    return expected;
  }
  catch(const GameActionError&) {
    throw;
  }
  catch(const nlohmann::detail::exception&) {
    throw GameActionError("schema-validation","Malformed action envelope");
  }
}

bool GameAction::operator==(const GameAction& other) const {
  return kind == other.kind && canvasX == other.canvasX && canvasY == other.canvasY;
}

bool GameAction::operator!=(const GameAction& other) const {
  return !(*this == other);
}
