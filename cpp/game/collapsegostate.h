#ifndef GAME_COLLAPSEGOSTATE_H_
#define GAME_COLLAPSEGOSTATE_H_

#include "../game/board.h"
#include "../game/positionalsuperko.h"

struct CollapseGoQuotas {
  int immortal;
  int doubleMove;
  int eightway;

  CollapseGoQuotas();
  CollapseGoQuotas(int immortalQuota, int doubleMoveQuota, int eightwayQuota);

  bool operator==(const CollapseGoQuotas& other) const;
  bool operator!=(const CollapseGoQuotas& other) const;
};

enum class CollapseGoAbility {
  IMMORTAL,
  DOUBLE_MOVE,
  EIGHTWAY,
};

class CollapseGoConfig {
public:
  CollapseGoConfig(int boardSize, const CollapseGoQuotas& blackQuotas, const CollapseGoQuotas& whiteQuotas);

  static CollapseGoConfig allZero(int boardSize);
  static CollapseGoConfig allOne(int boardSize);
  static int thresholdForBoardSize(int boardSize);

  int getBoardSize() const;
  int getThreshold() const;
  const CollapseGoQuotas& getInitialQuotas(Player pla) const;
  int getInitialQuota(Player pla, CollapseGoAbility ability) const;

  bool operator==(const CollapseGoConfig& other) const;
  bool operator!=(const CollapseGoConfig& other) const;

private:
  int boardSize;
  int threshold;
  CollapseGoQuotas blackQuotas;
  CollapseGoQuotas whiteQuotas;
};

enum class CollapseGoPhase {
  COLLAPSE_PLAY,
  ORDINARY_PLAY,
  TERMINAL,
};

enum class CollapseGoSettlementReason {
  NONE,
  THRESHOLD,
  PRE_THRESHOLD_TWO_PASSES,
};

struct CollapseGoScore {
  bool isScored;
  int blackStones;
  int whiteStones;
  int blackTerritory;
  int whiteTerritory;
  int blackScoreNumerator;
  int whiteScoreNumerator;
  Player winner;
  int marginNumerator;

  CollapseGoScore();

  double getBlackScore() const;
  double getWhiteScore() const;
  double getMargin() const;

  bool operator==(const CollapseGoScore& other) const;
  bool operator!=(const CollapseGoScore& other) const;
};

class CollapseGoState {
public:
  explicit CollapseGoState(const CollapseGoConfig& config);

  const CollapseGoConfig& getConfig() const;
  const Board& getBoard() const;
  CollapseGoPhase getPhase() const;
  Player getActor() const;
  int getAtomicActionCount() const;
  int getConsecutivePasses() const;
  bool isSettlementCompleted() const;
  int getRemainingQuota(Player pla, CollapseGoAbility ability) const;
  const PositionalSuperkoHistory& getPositionalSuperkoHistory() const;
  const CollapseGoScore& getScore() const;

  void checkConsistency() const;
  bool isEqualForTesting(const CollapseGoState& other) const;

private:
  CollapseGoConfig config;
  Board board;
  CollapseGoPhase phase;
  Player actor;
  int atomicActionCount;
  int consecutivePasses;
  bool settlementCompleted;
  CollapseGoQuotas blackRemainingQuotas;
  CollapseGoQuotas whiteRemainingQuotas;
  PositionalSuperkoHistory positionalSuperkoHistory;
  CollapseGoScore score;

  friend class CollapseGoReducer;
};

#endif // GAME_COLLAPSEGOSTATE_H_
