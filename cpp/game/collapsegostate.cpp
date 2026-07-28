#include "../game/collapsegostate.h"

using namespace std;

namespace {

void validateQuotaValue(int quota) {
  if(quota != 0 && quota != 1)
    throw StringError("Collapse Go slice quotas must be 0 or 1");
}

void validateQuotas(const CollapseGoQuotas& quotas) {
  validateQuotaValue(quotas.immortal);
  validateQuotaValue(quotas.doubleMove);
  validateQuotaValue(quotas.eightway);
}

int quotaForAbility(const CollapseGoQuotas& quotas, CollapseGoAbility ability) {
  switch(ability) {
  case CollapseGoAbility::IMMORTAL: return quotas.immortal;
  case CollapseGoAbility::DOUBLE_MOVE: return quotas.doubleMove;
  case CollapseGoAbility::EIGHTWAY: return quotas.eightway;
  default:
    throw StringError("Unknown Collapse Go ability");
  }
}

}

CollapseGoQuotas::CollapseGoQuotas()
  : immortal(0), doubleMove(0), eightway(0)
{}

CollapseGoQuotas::CollapseGoQuotas(int immortalQuota, int doubleMoveQuota, int eightwayQuota)
  : immortal(immortalQuota), doubleMove(doubleMoveQuota), eightway(eightwayQuota)
{}

bool CollapseGoQuotas::operator==(const CollapseGoQuotas& other) const {
  return immortal == other.immortal && doubleMove == other.doubleMove && eightway == other.eightway;
}

bool CollapseGoQuotas::operator!=(const CollapseGoQuotas& other) const {
  return !(*this == other);
}

CollapseGoConfig::CollapseGoConfig(
  int configBoardSize,
  const CollapseGoQuotas& configBlackQuotas,
  const CollapseGoQuotas& configWhiteQuotas
)
  : boardSize(configBoardSize),
    threshold(thresholdForBoardSize(configBoardSize)),
    blackQuotas(configBlackQuotas),
    whiteQuotas(configWhiteQuotas)
{
  validateQuotas(blackQuotas);
  validateQuotas(whiteQuotas);
}

CollapseGoConfig CollapseGoConfig::allZero(int boardSize) {
  return CollapseGoConfig(boardSize,CollapseGoQuotas(0,0,0),CollapseGoQuotas(0,0,0));
}

CollapseGoConfig CollapseGoConfig::allOne(int boardSize) {
  return CollapseGoConfig(boardSize,CollapseGoQuotas(1,1,1),CollapseGoQuotas(1,1,1));
}

int CollapseGoConfig::thresholdForBoardSize(int boardSize) {
  if(boardSize != 9 && boardSize != 13 && boardSize != 19)
    throw StringError("Collapse Go slice supports only 9x9, 13x13, and 19x19 boards");
  return (150 * boardSize * boardSize + 180) / 361;
}

int CollapseGoConfig::getBoardSize() const {
  return boardSize;
}

int CollapseGoConfig::getThreshold() const {
  return threshold;
}

const CollapseGoQuotas& CollapseGoConfig::getInitialQuotas(Player pla) const {
  if(pla == P_BLACK)
    return blackQuotas;
  if(pla == P_WHITE)
    return whiteQuotas;
  throw StringError("Collapse Go quota lookup requires Black or White");
}

int CollapseGoConfig::getInitialQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(getInitialQuotas(pla),ability);
}

bool CollapseGoConfig::operator==(const CollapseGoConfig& other) const {
  return boardSize == other.boardSize && threshold == other.threshold &&
    blackQuotas == other.blackQuotas && whiteQuotas == other.whiteQuotas;
}

bool CollapseGoConfig::operator!=(const CollapseGoConfig& other) const {
  return !(*this == other);
}

CollapseGoScore::CollapseGoScore()
  : isScored(false),
    blackStones(0),
    whiteStones(0),
    blackTerritory(0),
    whiteTerritory(0),
    blackScoreNumerator(0),
    whiteScoreNumerator(0),
    winner(C_EMPTY),
    marginNumerator(0)
{}

double CollapseGoScore::getBlackScore() const {
  return 0.5 * blackScoreNumerator;
}

double CollapseGoScore::getWhiteScore() const {
  return 0.5 * whiteScoreNumerator;
}

double CollapseGoScore::getMargin() const {
  return 0.5 * marginNumerator;
}

bool CollapseGoScore::operator==(const CollapseGoScore& other) const {
  return isScored == other.isScored &&
    blackStones == other.blackStones && whiteStones == other.whiteStones &&
    blackTerritory == other.blackTerritory && whiteTerritory == other.whiteTerritory &&
    blackScoreNumerator == other.blackScoreNumerator && whiteScoreNumerator == other.whiteScoreNumerator &&
    winner == other.winner && marginNumerator == other.marginNumerator;
}

bool CollapseGoScore::operator!=(const CollapseGoScore& other) const {
  return !(*this == other);
}

CollapseGoState::CollapseGoState(const CollapseGoConfig& stateConfig)
  : config(stateConfig),
    board(stateConfig.getBoardSize(),stateConfig.getBoardSize()),
    phase(CollapseGoPhase::COLLAPSE_PLAY),
    actor(P_BLACK),
    atomicActionCount(0),
    consecutivePasses(0),
    settlementCompleted(false),
    blackRemainingQuotas(stateConfig.getInitialQuotas(P_BLACK)),
    whiteRemainingQuotas(stateConfig.getInitialQuotas(P_WHITE)),
    positionalSuperkoHistory(board),
    score()
{
  checkConsistency();
}

const CollapseGoConfig& CollapseGoState::getConfig() const {
  return config;
}

const Board& CollapseGoState::getBoard() const {
  return board;
}

CollapseGoPhase CollapseGoState::getPhase() const {
  return phase;
}

Player CollapseGoState::getActor() const {
  return actor;
}

int CollapseGoState::getAtomicActionCount() const {
  return atomicActionCount;
}

int CollapseGoState::getConsecutivePasses() const {
  return consecutivePasses;
}

bool CollapseGoState::isSettlementCompleted() const {
  return settlementCompleted;
}

int CollapseGoState::getRemainingQuota(Player pla, CollapseGoAbility ability) const {
  const CollapseGoQuotas* quotas;
  if(pla == P_BLACK)
    quotas = &blackRemainingQuotas;
  else if(pla == P_WHITE)
    quotas = &whiteRemainingQuotas;
  else
    throw StringError("Collapse Go quota lookup requires Black or White");
  return quotaForAbility(*quotas,ability);
}

const PositionalSuperkoHistory& CollapseGoState::getPositionalSuperkoHistory() const {
  return positionalSuperkoHistory;
}

const CollapseGoScore& CollapseGoState::getScore() const {
  return score;
}

void CollapseGoState::checkConsistency() const {
  if(atomicActionCount < 0)
    throw StringError("Collapse Go atomic action count is negative");

  size_t expectedHistorySize = static_cast<size_t>(atomicActionCount) + 1;
  if(phase == CollapseGoPhase::TERMINAL) {
    if(!score.isScored)
      throw StringError("Collapse Go slice terminal state must have a score");
    expectedHistorySize++;
  }
  else if(score.isScored)
    throw StringError("Collapse Go nonterminal state cannot have a terminal score");

  if(positionalSuperkoHistory.size() != expectedHistorySize)
    throw StringError("Collapse Go PSK history size is inconsistent with committed atomic actions");
  if(positionalSuperkoHistory.back() != PositionalSuperkoKey(board))
    throw StringError("Collapse Go PSK history does not end at the visible board occupancy");
}

bool CollapseGoState::isEqualForTesting(const CollapseGoState& other) const {
  return config == other.config &&
    board.isEqualForTesting(other.board) &&
    phase == other.phase && actor == other.actor &&
    atomicActionCount == other.atomicActionCount && consecutivePasses == other.consecutivePasses &&
    settlementCompleted == other.settlementCompleted &&
    blackRemainingQuotas == other.blackRemainingQuotas && whiteRemainingQuotas == other.whiteRemainingQuotas &&
    positionalSuperkoHistory == other.positionalSuperkoHistory && score == other.score;
}
