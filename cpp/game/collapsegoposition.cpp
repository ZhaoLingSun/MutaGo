#include "../game/collapsegoposition.h"

using namespace std;

CollapseGoStoneSource::CollapseGoStoneSource()
  : originActionNumber(0), originKind(GameActionKind::NORMAL), specialLink()
{}

CollapseGoStoneSource::CollapseGoStoneSource(
  int64_t sourceOriginActionNumber,
  GameActionKind sourceOriginKind,
  const optional<int64_t>& sourceSpecialLink
)
  : originActionNumber(sourceOriginActionNumber),
    originKind(sourceOriginKind),
    specialLink(sourceSpecialLink)
{
  checkConsistency();
}

void CollapseGoStoneSource::checkConsistency() const {
  if(originActionNumber <= 0)
    throw StringError("Collapse Go stone source action number must be positive");
  if(!GameAction::isPointKind(originKind))
    throw StringError("Collapse Go stone source must originate from a point action");
  if(originKind == GameActionKind::NORMAL) {
    if(specialLink.has_value())
      throw StringError("Collapse Go NORMAL stone source cannot have a special link");
  }
  else {
    if(!specialLink.has_value() || *specialLink < 0)
      throw StringError("Collapse Go special stone source requires a nonnegative special link");
  }
}

bool CollapseGoStoneSource::operator==(const CollapseGoStoneSource& other) const {
  return originActionNumber == other.originActionNumber &&
    originKind == other.originKind && specialLink == other.specialLink;
}

bool CollapseGoStoneSource::operator!=(const CollapseGoStoneSource& other) const {
  return !(*this == other);
}

CollapseGoCell::CollapseGoCell()
  : color(C_EMPTY), source()
{}

CollapseGoCell::CollapseGoCell(Color cellColor, const CollapseGoStoneSource& cellSource)
  : color(cellColor), source(cellSource)
{}

bool CollapseGoCell::isOccupied() const {
  return color == C_BLACK || color == C_WHITE;
}

Color CollapseGoCell::getColor() const {
  return color;
}

const CollapseGoStoneSource& CollapseGoCell::getSource() const {
  if(!source.has_value())
    throw StringError("Empty Collapse Go cell has no stone source");
  return *source;
}

void CollapseGoCell::clear() {
  color = C_EMPTY;
  source.reset();
}

bool CollapseGoCell::operator==(const CollapseGoCell& other) const {
  return color == other.color && source == other.source;
}

bool CollapseGoCell::operator!=(const CollapseGoCell& other) const {
  return !(*this == other);
}

CollapseGoPosition::CollapseGoPosition(int positionBoardSize)
  : boardSize(positionBoardSize), cells()
{
  if(boardSize <= 0 || boardSize > GameAction::CANVAS_SIZE)
    throw StringError("Collapse Go position board size must be within 1..19");
  cells.resize(static_cast<size_t>(boardSize * boardSize));
  checkConsistency();
}

int CollapseGoPosition::getBoardSize() const {
  return boardSize;
}

int CollapseGoPosition::getPointCount() const {
  return boardSize * boardSize;
}

bool CollapseGoPosition::isOnBoard(int x, int y) const {
  return x >= 0 && x < boardSize && y >= 0 && y < boardSize;
}

bool CollapseGoPosition::isValidPoint(int point) const {
  return point >= 0 && point < getPointCount();
}

int CollapseGoPosition::getPoint(int x, int y) const {
  if(!isOnBoard(x,y))
    throw StringError("Collapse Go coordinate is off board");
  return y * boardSize + x;
}

void CollapseGoPosition::requirePoint(int point) const {
  if(!isValidPoint(point))
    throw StringError("Collapse Go row-major point is off board");
}

int CollapseGoPosition::getX(int point) const {
  requirePoint(point);
  return point % boardSize;
}

int CollapseGoPosition::getY(int point) const {
  requirePoint(point);
  return point / boardSize;
}

const CollapseGoCell& CollapseGoPosition::getCell(int point) const {
  requirePoint(point);
  return cells[static_cast<size_t>(point)];
}

const CollapseGoCell& CollapseGoPosition::getCell(int x, int y) const {
  return getCell(getPoint(x,y));
}

Color CollapseGoPosition::getColor(int point) const {
  return getCell(point).getColor();
}

Color CollapseGoPosition::getColor(int x, int y) const {
  return getCell(x,y).getColor();
}

bool CollapseGoPosition::isEmpty(int point) const {
  return getColor(point) == C_EMPTY;
}

bool CollapseGoPosition::isEmpty(int x, int y) const {
  return getColor(x,y) == C_EMPTY;
}

void CollapseGoPosition::placeStone(int point, Player color, const CollapseGoStoneSource& stoneSource) {
  requirePoint(point);
  if(color != P_BLACK && color != P_WHITE)
    throw StringError("Collapse Go stone color must be Black or White");
  if(!cells[static_cast<size_t>(point)].isOccupied()) {
    stoneSource.checkConsistency();
    cells[static_cast<size_t>(point)] = CollapseGoCell(color,stoneSource);
    return;
  }
  throw StringError("Cannot place a Collapse Go stone on an occupied point");
}

void CollapseGoPosition::placeStone(
  int x,
  int y,
  Player color,
  const CollapseGoStoneSource& stoneSource
) {
  placeStone(getPoint(x,y),color,stoneSource);
}

void CollapseGoPosition::removeStone(int point) {
  requirePoint(point);
  cells[static_cast<size_t>(point)].clear();
}

void CollapseGoPosition::removeStones(const vector<int>& points) {
  vector<bool> seen(static_cast<size_t>(getPointCount()),false);
  for(int point: points) {
    requirePoint(point);
    if(seen[static_cast<size_t>(point)])
      throw StringError("Collapse Go stone removal list contains a duplicate point");
    seen[static_cast<size_t>(point)] = true;
  }
  for(int point: points)
    cells[static_cast<size_t>(point)].clear();
}

vector<uint8_t> CollapseGoPosition::getRowMajorOccupancy() const {
  vector<uint8_t> occupancy;
  occupancy.reserve(cells.size());
  for(const CollapseGoCell& cell: cells)
    occupancy.push_back(static_cast<uint8_t>(cell.getColor()));
  return occupancy;
}

int CollapseGoPosition::countStones(Player color) const {
  if(color != P_BLACK && color != P_WHITE)
    throw StringError("Collapse Go stone count requires Black or White");
  int count = 0;
  for(const CollapseGoCell& cell: cells) {
    if(cell.getColor() == color)
      count++;
  }
  return count;
}

void CollapseGoPosition::checkConsistency() const {
  if(boardSize <= 0 || boardSize > GameAction::CANVAS_SIZE)
    throw StringError("Collapse Go position has an invalid board size");
  if(cells.size() != static_cast<size_t>(boardSize * boardSize))
    throw StringError("Collapse Go position cell count does not match board size");
  for(const CollapseGoCell& cell: cells) {
    Color color = cell.getColor();
    if(color == C_EMPTY) {
      if(cell.source.has_value())
        throw StringError("Empty Collapse Go cell retains a stone source");
    }
    else if(color == C_BLACK || color == C_WHITE) {
      if(!cell.source.has_value())
        throw StringError("Occupied Collapse Go cell is missing a stone source");
      cell.source->checkConsistency();
    }
    else
      throw StringError("Collapse Go position contains a non-playable color");
  }
}

bool CollapseGoPosition::isEqualForTesting(const CollapseGoPosition& other) const {
  return boardSize == other.boardSize && cells == other.cells;
}
