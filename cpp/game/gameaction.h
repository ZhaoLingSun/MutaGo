#ifndef GAME_GAMEACTION_H_
#define GAME_GAMEACTION_H_

#include "../core/global.h"
#include "../external/nlohmann_json/json.hpp"

struct GameActionError final : public StringError {
  std::string code;

  GameActionError(const std::string& errorCode, const std::string& errorMessage);
  const std::string& getCode() const;
};

enum class GameActionKind {
  NORMAL = 0,
  IMMORTAL = 1,
  DOUBLE_START = 2,
  EIGHTWAY = 3,
  PASS = 4,
};

class GameAction {
public:
  static constexpr int CANVAS_SIZE = 19;
  static constexpr int CANVAS_POINT_COUNT = 361;
  static constexpr int KIND_STRIDE = 361;
  static constexpr int POINT_KIND_COUNT = 4;
  static constexpr int FLAT_ACTION_COUNT = 1445;
  static constexpr int PASS_ACTION_ID = 1444;
  static constexpr int SYMMETRY_COUNT = 8;
  static const std::string ACTION_SCHEMA_SHA256;

  static GameAction pass();
  static GameAction fromCanvas(GameActionKind kind, int canvasX, int canvasY);
  static GameAction fromCanvas(const nlohmann::json& kind, const nlohmann::json& canvasX, const nlohmann::json& canvasY);
  static GameAction fromBoard(GameActionKind kind, int boardSize, int x, int y);
  static GameAction fromBoard(
    const nlohmann::json& kind,
    const nlohmann::json& boardSize,
    const nlohmann::json& x,
    const nlohmann::json& y
  );
  static GameAction decode(int actionId);
  static GameAction decode(const nlohmann::json& actionId);
  static GameAction decodeForBoard(int actionId, int boardSize);
  static GameAction decodeForBoard(const nlohmann::json& actionId, const nlohmann::json& boardSize);
  static GameAction ofJson(const nlohmann::json& value);

  static GameActionKind parseKind(const std::string& name);
  static std::string kindToString(GameActionKind kind);
  static int kindCode(GameActionKind kind);
  static bool isPointKind(GameActionKind kind);

  static bool isSupportedBoardSize(int boardSize);
  static int boardOffset(int boardSize);
  static int inverseSymmetry(int symmetryId);

  GameActionKind getKind() const;
  int getCanvasX() const;
  int getCanvasY() const;
  int getActionId() const;
  bool isPass() const;

  bool isInBoardFootprint(int boardSize) const;
  int getBoardX(int boardSize) const;
  int getBoardY(int boardSize) const;

  GameAction transformed(int symmetryId) const;
  nlohmann::json toJson() const;

  bool operator==(const GameAction& other) const;
  bool operator!=(const GameAction& other) const;

private:
  GameActionKind kind;
  int canvasX;
  int canvasY;

  GameAction(GameActionKind actionKind, int actionCanvasX, int actionCanvasY);
  static int64_t requireJsonInteger(const nlohmann::json& value, const std::string& fieldName);
  static GameActionKind requireJsonKind(const nlohmann::json& value);
  static void requireCanvasPoint(int canvasX, int canvasY);
  static void requireSymmetry(int symmetryId);
};

#endif // GAME_GAMEACTION_H_
