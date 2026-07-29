#ifndef GAME_COLLAPSEGOSTATE_H_
#define GAME_COLLAPSEGOSTATE_H_

#include <cstdint>
#include <optional>
#include <vector>

#include "../game/collapsegoposition.h"
#include "../game/positionalsuperko.h"

class CollapseGoStateTestAccess;

struct CollapseGoQuotas {
  int64_t immortal;
  int64_t doubleMove;
  int64_t eightway;

  CollapseGoQuotas();
  CollapseGoQuotas(int64_t immortalQuota, int64_t doubleMoveQuota, int64_t eightwayQuota);

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
  int64_t getInitialQuota(Player pla, CollapseGoAbility ability) const;

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

enum class CollapseGoLedgerAbilityState {
  CONSUMED,
  INACTIVE,
};

enum class CollapseGoLedgerStoneState {
  ON_BOARD,
  CAPTURED,
};

enum class CollapseGoLedgerSettlementState {
  PENDING,
  SETTLED,
};

struct CollapseGoLedgerEntry {
  int64_t specialLink;
  int64_t originActionNumber;
  Player owner;
  GameActionKind originKind;
  int sourcePoint;
  CollapseGoLedgerAbilityState abilityState;
  CollapseGoLedgerStoneState stoneState;
  CollapseGoLedgerSettlementState settlementState;
  bool tombstone;

  CollapseGoLedgerEntry(
    int64_t entrySpecialLink,
    int64_t entryOriginActionNumber,
    Player entryOwner,
    GameActionKind entryOriginKind,
    int entrySourcePoint
  );

  bool operator==(const CollapseGoLedgerEntry& other) const;
  bool operator!=(const CollapseGoLedgerEntry& other) const;
};

class CollapseGoLedger {
public:
  CollapseGoLedger();

  size_t size() const;
  bool empty() const;
  const CollapseGoLedgerEntry& at(size_t index) const;

  bool operator==(const CollapseGoLedger& other) const;
  bool operator!=(const CollapseGoLedger& other) const;

private:
  std::vector<CollapseGoLedgerEntry> entries;

  void append(const CollapseGoLedgerEntry& entry);

  friend class CollapseGoReducer;
  friend class CollapseGoStateTestAccess;
};

struct CollapseGoPendingDouble {
  Player owner;
  int64_t specialLink;
  int64_t originActionNumber;

  CollapseGoPendingDouble(Player pendingOwner, int64_t pendingSpecialLink, int64_t pendingOriginActionNumber);

  bool operator==(const CollapseGoPendingDouble& other) const;
  bool operator!=(const CollapseGoPendingDouble& other) const;
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
  CollapseGoState(const CollapseGoState&) = default;
  CollapseGoState(CollapseGoState&&) noexcept = default;

  const CollapseGoConfig& getConfig() const;
  const CollapseGoPosition& getPosition() const;
  CollapseGoPhase getPhase() const;
  Player getActor() const;
  int64_t getAtomicActionCount() const;
  int getConsecutivePasses() const;
  bool isSettlementCompleted() const;
  int64_t getInitialQuota(Player pla, CollapseGoAbility ability) const;
  int64_t getRemainingQuota(Player pla, CollapseGoAbility ability) const;
  int64_t getUsedQuota(Player pla, CollapseGoAbility ability) const;
  int64_t getExpiredQuota(Player pla, CollapseGoAbility ability) const;
  const CollapseGoLedger& getLedger() const;
  const std::optional<CollapseGoPendingDouble>& getPendingDouble() const;
  int64_t getRevision() const;
  int64_t getLogPosition() const;
  int64_t getSettledLedgerCount() const;
  int64_t getStableTerminalEventCount() const;
  const PositionalSuperkoHistory& getPositionalSuperkoHistory() const;
  const CollapseGoScore& getScore() const;

  void checkConsistency() const;
  bool isEqualForTesting(const CollapseGoState& other) const;
  CollapseGoState& operator=(CollapseGoState other);

private:
  CollapseGoConfig config;
  CollapseGoPosition position;
  CollapseGoPhase phase;
  Player actor;
  int64_t atomicActionCount;
  int consecutivePasses;
  bool settlementCompleted;
  CollapseGoQuotas blackInitialQuotas;
  CollapseGoQuotas whiteInitialQuotas;
  CollapseGoQuotas blackRemainingQuotas;
  CollapseGoQuotas whiteRemainingQuotas;
  CollapseGoQuotas blackUsedQuotas;
  CollapseGoQuotas whiteUsedQuotas;
  CollapseGoQuotas blackExpiredQuotas;
  CollapseGoQuotas whiteExpiredQuotas;
  CollapseGoLedger ledger;
  std::optional<CollapseGoPendingDouble> pendingDouble;
  int64_t revision;
  int64_t logPosition;
  int64_t settledLedgerCount;
  int64_t stableTerminalEventCount;
  PositionalSuperkoHistory positionalSuperkoHistory;
  CollapseGoScore score;

  void swap(CollapseGoState& other) noexcept;

  friend class CollapseGoReducer;
  friend class CollapseGoStateTestAccess;
};

#endif // GAME_COLLAPSEGOSTATE_H_
