#include "../game/collapsegostate.h"

#include <set>

#include "../game/collapsegotopology.h"

using namespace std;

namespace {

static constexpr int64_t COLLAPSE_GO_SAFE_INTEGER_MAX = 9007199254740991LL;

void validateQuotaValue(int64_t quota) {
  if(quota < 0 || quota > COLLAPSE_GO_SAFE_INTEGER_MAX)
    throw StringError("Collapse Go quotas must be nonnegative JSON safe integers");
}

void validateQuotas(const CollapseGoQuotas& quotas) {
  validateQuotaValue(quotas.immortal);
  validateQuotaValue(quotas.doubleMove);
  validateQuotaValue(quotas.eightway);
}

int64_t quotaForAbility(const CollapseGoQuotas& quotas, CollapseGoAbility ability) {
  switch(ability) {
  case CollapseGoAbility::IMMORTAL: return quotas.immortal;
  case CollapseGoAbility::DOUBLE_MOVE: return quotas.doubleMove;
  case CollapseGoAbility::EIGHTWAY: return quotas.eightway;
  default:
    throw StringError("Unknown Collapse Go ability");
  }
}

const CollapseGoQuotas& quotasForPlayer(
  Player pla,
  const CollapseGoQuotas& blackQuotas,
  const CollapseGoQuotas& whiteQuotas
) {
  if(pla == P_BLACK)
    return blackQuotas;
  if(pla == P_WHITE)
    return whiteQuotas;
  throw StringError("Collapse Go quota lookup requires Black or White");
}

void checkQuotaConservation(
  const CollapseGoQuotas& initial,
  const CollapseGoQuotas& remaining,
  const CollapseGoQuotas& used,
  const CollapseGoQuotas& expired
) {
  validateQuotas(initial);
  validateQuotas(remaining);
  validateQuotas(used);
  validateQuotas(expired);
  for(CollapseGoAbility ability: {
    CollapseGoAbility::IMMORTAL,
    CollapseGoAbility::DOUBLE_MOVE,
    CollapseGoAbility::EIGHTWAY,
  }) {
    int64_t initialValue = quotaForAbility(initial,ability);
    int64_t remainingValue = quotaForAbility(remaining,ability);
    int64_t usedValue = quotaForAbility(used,ability);
    int64_t expiredValue = quotaForAbility(expired,ability);
    if(usedValue > initialValue || expiredValue > initialValue - usedValue ||
       remainingValue != initialValue - usedValue - expiredValue)
      throw StringError("Collapse Go quota conservation is inconsistent");
  }
}

}

CollapseGoQuotas::CollapseGoQuotas()
  : immortal(0), doubleMove(0), eightway(0)
{}

CollapseGoQuotas::CollapseGoQuotas(
  int64_t immortalQuota,
  int64_t doubleMoveQuota,
  int64_t eightwayQuota
)
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
  return quotasForPlayer(pla,blackQuotas,whiteQuotas);
}

int64_t CollapseGoConfig::getInitialQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(getInitialQuotas(pla),ability);
}

bool CollapseGoConfig::operator==(const CollapseGoConfig& other) const {
  return boardSize == other.boardSize && threshold == other.threshold &&
    blackQuotas == other.blackQuotas && whiteQuotas == other.whiteQuotas;
}

bool CollapseGoConfig::operator!=(const CollapseGoConfig& other) const {
  return !(*this == other);
}

CollapseGoLedgerEntry::CollapseGoLedgerEntry(
  int64_t entrySpecialLink,
  int64_t entryOriginActionNumber,
  Player entryOwner,
  GameActionKind entryOriginKind,
  int entrySourcePoint
)
  : specialLink(entrySpecialLink),
    originActionNumber(entryOriginActionNumber),
    owner(entryOwner),
    originKind(entryOriginKind),
    sourcePoint(entrySourcePoint)
{
  if(specialLink < 0 || originActionNumber <= 0 || sourcePoint < 0)
    throw StringError("Collapse Go ledger entry has an invalid identity");
  if(owner != P_BLACK && owner != P_WHITE)
    throw StringError("Collapse Go ledger entry owner must be Black or White");
  if(originKind != GameActionKind::IMMORTAL &&
     originKind != GameActionKind::DOUBLE_START &&
     originKind != GameActionKind::EIGHTWAY)
    throw StringError("Collapse Go ledger entry must reference a special action");
}

bool CollapseGoLedgerEntry::operator==(const CollapseGoLedgerEntry& other) const {
  return specialLink == other.specialLink && originActionNumber == other.originActionNumber &&
    owner == other.owner && originKind == other.originKind && sourcePoint == other.sourcePoint;
}

bool CollapseGoLedgerEntry::operator!=(const CollapseGoLedgerEntry& other) const {
  return !(*this == other);
}

CollapseGoLedger::CollapseGoLedger()
  : entries()
{}

size_t CollapseGoLedger::size() const {
  return entries.size();
}

bool CollapseGoLedger::empty() const {
  return entries.empty();
}

const CollapseGoLedgerEntry& CollapseGoLedger::at(size_t index) const {
  return entries.at(index);
}

void CollapseGoLedger::append(const CollapseGoLedgerEntry& entry) {
  if(!entries.empty() && entry.originActionNumber <= entries.back().originActionNumber)
    throw StringError("Collapse Go ledger entries must be appended in action order");
  for(const CollapseGoLedgerEntry& existing: entries) {
    if(existing.specialLink == entry.specialLink)
      throw StringError("Collapse Go ledger special links must be unique");
  }
  entries.push_back(entry);
}

bool CollapseGoLedger::operator==(const CollapseGoLedger& other) const {
  return entries == other.entries;
}

bool CollapseGoLedger::operator!=(const CollapseGoLedger& other) const {
  return !(*this == other);
}

CollapseGoPendingDouble::CollapseGoPendingDouble(
  Player pendingOwner,
  int64_t pendingSpecialLink,
  int64_t pendingOriginActionNumber
)
  : owner(pendingOwner), specialLink(pendingSpecialLink), originActionNumber(pendingOriginActionNumber)
{
  if(owner != P_BLACK && owner != P_WHITE)
    throw StringError("Collapse Go pending Double owner must be Black or White");
  if(specialLink < 0 || originActionNumber <= 0)
    throw StringError("Collapse Go pending Double identity is invalid");
}

bool CollapseGoPendingDouble::operator==(const CollapseGoPendingDouble& other) const {
  return owner == other.owner && specialLink == other.specialLink &&
    originActionNumber == other.originActionNumber;
}

bool CollapseGoPendingDouble::operator!=(const CollapseGoPendingDouble& other) const {
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
    position(stateConfig.getBoardSize()),
    phase(CollapseGoPhase::COLLAPSE_PLAY),
    actor(P_BLACK),
    atomicActionCount(0),
    consecutivePasses(0),
    settlementCompleted(false),
    blackInitialQuotas(stateConfig.getInitialQuotas(P_BLACK)),
    whiteInitialQuotas(stateConfig.getInitialQuotas(P_WHITE)),
    blackRemainingQuotas(blackInitialQuotas),
    whiteRemainingQuotas(whiteInitialQuotas),
    blackUsedQuotas(),
    whiteUsedQuotas(),
    blackExpiredQuotas(),
    whiteExpiredQuotas(),
    ledger(),
    pendingDouble(),
    revision(0),
    logPosition(0),
    settledLedgerCount(0),
    stableTerminalEventCount(0),
    positionalSuperkoHistory(position.getBoardSize(),position.getRowMajorOccupancy()),
    score()
{
  checkConsistency();
}

const CollapseGoConfig& CollapseGoState::getConfig() const {
  return config;
}

const CollapseGoPosition& CollapseGoState::getPosition() const {
  return position;
}

CollapseGoPhase CollapseGoState::getPhase() const {
  return phase;
}

Player CollapseGoState::getActor() const {
  return actor;
}

int64_t CollapseGoState::getAtomicActionCount() const {
  return atomicActionCount;
}

int CollapseGoState::getConsecutivePasses() const {
  return consecutivePasses;
}

bool CollapseGoState::isSettlementCompleted() const {
  return settlementCompleted;
}

int64_t CollapseGoState::getInitialQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(quotasForPlayer(pla,blackInitialQuotas,whiteInitialQuotas),ability);
}

int64_t CollapseGoState::getRemainingQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(quotasForPlayer(pla,blackRemainingQuotas,whiteRemainingQuotas),ability);
}

int64_t CollapseGoState::getUsedQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(quotasForPlayer(pla,blackUsedQuotas,whiteUsedQuotas),ability);
}

int64_t CollapseGoState::getExpiredQuota(Player pla, CollapseGoAbility ability) const {
  return quotaForAbility(quotasForPlayer(pla,blackExpiredQuotas,whiteExpiredQuotas),ability);
}

const CollapseGoLedger& CollapseGoState::getLedger() const {
  return ledger;
}

const optional<CollapseGoPendingDouble>& CollapseGoState::getPendingDouble() const {
  return pendingDouble;
}

int64_t CollapseGoState::getRevision() const {
  return revision;
}

int64_t CollapseGoState::getLogPosition() const {
  return logPosition;
}

int64_t CollapseGoState::getSettledLedgerCount() const {
  return settledLedgerCount;
}

int64_t CollapseGoState::getStableTerminalEventCount() const {
  return stableTerminalEventCount;
}

const PositionalSuperkoHistory& CollapseGoState::getPositionalSuperkoHistory() const {
  return positionalSuperkoHistory;
}

const CollapseGoScore& CollapseGoState::getScore() const {
  return score;
}

void CollapseGoState::checkConsistency() const {
  position.checkConsistency();
  if(position.getBoardSize() != config.getBoardSize())
    throw StringError("Collapse Go position size does not match the configuration");
  if(atomicActionCount < 0 || revision < 0 || logPosition < 0 ||
     settledLedgerCount < 0 || stableTerminalEventCount < 0)
    throw StringError("Collapse Go state counters must be nonnegative");
  if(revision != atomicActionCount)
    throw StringError("Collapse Go revision must equal accepted command count in Increment 0");
  if(stableTerminalEventCount != 0 && stableTerminalEventCount != 1)
    throw StringError("Collapse Go Increment 0 terminal event count must be zero or one");
  if(settledLedgerCount > static_cast<int64_t>(ledger.size()))
    throw StringError("Collapse Go settled ledger count exceeds ledger size");
  if(logPosition != atomicActionCount + settledLedgerCount + stableTerminalEventCount)
    throw StringError("Collapse Go log position is inconsistent with committed stable events");

  if(blackInitialQuotas != config.getInitialQuotas(P_BLACK) ||
     whiteInitialQuotas != config.getInitialQuotas(P_WHITE))
    throw StringError("Collapse Go state initial quotas do not match the configuration");
  checkQuotaConservation(blackInitialQuotas,blackRemainingQuotas,blackUsedQuotas,blackExpiredQuotas);
  checkQuotaConservation(whiteInitialQuotas,whiteRemainingQuotas,whiteUsedQuotas,whiteExpiredQuotas);

  if(!ledger.empty() || settledLedgerCount != 0 || pendingDouble.has_value())
    throw StringError("Collapse Go Increment 0 requires an empty ledger and null pending Double");
  if(blackUsedQuotas != CollapseGoQuotas() || whiteUsedQuotas != CollapseGoQuotas())
    throw StringError("Collapse Go Increment 0 cannot contain used special quotas");

  if(phase == CollapseGoPhase::COLLAPSE_PLAY) {
    if(settlementCompleted)
      throw StringError("Collapse Go pre-settlement phase cannot be marked settled");
    if(atomicActionCount >= config.getThreshold())
      throw StringError("Collapse Go exposed pre-settlement state reached its threshold");
    if(consecutivePasses < 0 || consecutivePasses > 1)
      throw StringError("Collapse Go pre-settlement pass streak must be zero or one");
    if(blackExpiredQuotas != CollapseGoQuotas() || whiteExpiredQuotas != CollapseGoQuotas())
      throw StringError("Collapse Go quotas cannot expire before settlement");
  }
  else {
    if(!settlementCompleted)
      throw StringError("Collapse Go post-settlement state must be marked settled");
    if(blackRemainingQuotas != CollapseGoQuotas() || whiteRemainingQuotas != CollapseGoQuotas())
      throw StringError("Collapse Go remaining quotas must be zero after settlement");
    if(consecutivePasses < 0 || consecutivePasses > 2)
      throw StringError("Collapse Go post-settlement pass streak is invalid");
  }

  if(phase == CollapseGoPhase::TERMINAL) {
    if(!score.isScored || actor != C_EMPTY || stableTerminalEventCount != 1 || consecutivePasses != 2)
      throw StringError("Collapse Go scored terminal state is incomplete");
  }
  else {
    if(score.isScored || stableTerminalEventCount != 0)
      throw StringError("Collapse Go nonterminal state cannot have a terminal score event");
    if(actor != P_BLACK && actor != P_WHITE)
      throw StringError("Collapse Go nonterminal actor must be Black or White");
  }

  CollapseGoTopology topology = CollapseGoTopology::fullScanN4(position);
  for(const CollapseGoGroup& group: topology.getGroups()) {
    if(group.liberties.empty())
      throw StringError("Collapse Go Increment 0 stable position contains a zero-liberty group");
  }

  set<int64_t> survivingOriginActions;
  for(int point = 0; point < position.getPointCount(); point++) {
    const CollapseGoCell& cell = position.getCell(point);
    if(!cell.isOccupied())
      continue;
    const CollapseGoStoneSource& source = cell.getSource();
    if(source.originActionNumber > atomicActionCount)
      throw StringError("Collapse Go stone source refers to an uncommitted action");
    if(source.originKind != GameActionKind::NORMAL || source.specialLink.has_value())
      throw StringError("Collapse Go Increment 0 supports only NORMAL stone sources");
    if(!survivingOriginActions.insert(source.originActionNumber).second)
      throw StringError("Collapse Go surviving stones share an origin action identity");
  }

  int64_t expectedHistorySize = 1 + atomicActionCount + settledLedgerCount + stableTerminalEventCount;
  if(positionalSuperkoHistory.size() != static_cast<size_t>(expectedHistorySize))
    throw StringError("Collapse Go PSK history size is inconsistent with stable events");
  for(size_t historyIndex = 0; historyIndex < positionalSuperkoHistory.size(); historyIndex++) {
    const PositionalSuperkoKey& historyKey = positionalSuperkoHistory.at(historyIndex);
    if(historyKey.getXSize() != position.getBoardSize() || historyKey.getYSize() != position.getBoardSize())
      throw StringError("Collapse Go PSK history contains a key for another board size");
  }
  PositionalSuperkoKey currentKey(position.getBoardSize(),position.getRowMajorOccupancy());
  if(positionalSuperkoHistory.back() != currentKey)
    throw StringError("Collapse Go PSK history does not end at the visible exact occupancy");
}

bool CollapseGoState::isEqualForTesting(const CollapseGoState& other) const {
  return config == other.config && position.isEqualForTesting(other.position) &&
    phase == other.phase && actor == other.actor &&
    atomicActionCount == other.atomicActionCount && consecutivePasses == other.consecutivePasses &&
    settlementCompleted == other.settlementCompleted &&
    blackInitialQuotas == other.blackInitialQuotas && whiteInitialQuotas == other.whiteInitialQuotas &&
    blackRemainingQuotas == other.blackRemainingQuotas && whiteRemainingQuotas == other.whiteRemainingQuotas &&
    blackUsedQuotas == other.blackUsedQuotas && whiteUsedQuotas == other.whiteUsedQuotas &&
    blackExpiredQuotas == other.blackExpiredQuotas && whiteExpiredQuotas == other.whiteExpiredQuotas &&
    ledger == other.ledger && pendingDouble == other.pendingDouble &&
    revision == other.revision && logPosition == other.logPosition &&
    settledLedgerCount == other.settledLedgerCount &&
    stableTerminalEventCount == other.stableTerminalEventCount &&
    positionalSuperkoHistory == other.positionalSuperkoHistory && score == other.score;
}
