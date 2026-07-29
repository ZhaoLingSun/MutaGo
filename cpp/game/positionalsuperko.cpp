#include "../game/positionalsuperko.h"

using namespace std;

PositionalSuperkoKey::PositionalSuperkoKey(
  int boardSize,
  const vector<uint8_t>& rowMajorOccupancy
)
  : PositionalSuperkoKey(boardSize,boardSize,rowMajorOccupancy)
{}

PositionalSuperkoKey::PositionalSuperkoKey(
  int keyXSize,
  int keyYSize,
  const vector<uint8_t>& rowMajorOccupancy
)
  : xSize(keyXSize), ySize(keyYSize), occupancy(rowMajorOccupancy)
{
  checkConsistency();
}

PositionalSuperkoKey::PositionalSuperkoKey(const Board& board)
  : xSize(board.x_size), ySize(board.y_size), occupancy()
{
  occupancy.reserve(static_cast<size_t>(xSize * ySize));
  for(int y = 0; y < ySize; y++) {
    for(int x = 0; x < xSize; x++) {
      Loc loc = Location::getLoc(x,y,xSize);
      occupancy.push_back(static_cast<uint8_t>(board.colors[loc]));
    }
  }
  checkConsistency();
}

void PositionalSuperkoKey::checkConsistency() const {
  if(xSize <= 0 || ySize <= 0)
    throw StringError("Positional superko key requires positive board dimensions");
  if(occupancy.size() != static_cast<size_t>(xSize * ySize))
    throw StringError("Positional superko key occupancy size does not match board dimensions");
  for(uint8_t color: occupancy) {
    if(color != C_EMPTY && color != C_BLACK && color != C_WHITE)
      throw StringError("Positional superko key requires playable occupancy");
  }
}

int PositionalSuperkoKey::getXSize() const {
  return xSize;
}

int PositionalSuperkoKey::getYSize() const {
  return ySize;
}

const vector<uint8_t>& PositionalSuperkoKey::getOccupancy() const {
  return occupancy;
}

bool PositionalSuperkoKey::operator==(const PositionalSuperkoKey& other) const {
  return xSize == other.xSize && ySize == other.ySize && occupancy == other.occupancy;
}

bool PositionalSuperkoKey::operator!=(const PositionalSuperkoKey& other) const {
  return !(*this == other);
}

PositionalSuperkoHistory::PositionalSuperkoHistory(const PositionalSuperkoKey& initialKey)
  : entries(1,initialKey)
{}

PositionalSuperkoHistory::PositionalSuperkoHistory(
  int boardSize,
  const vector<uint8_t>& initialRowMajorOccupancy
)
  : entries()
{
  entries.emplace_back(boardSize,initialRowMajorOccupancy);
}

PositionalSuperkoHistory::PositionalSuperkoHistory(const Board& initialBoard)
  : entries()
{
  entries.emplace_back(initialBoard);
}

size_t PositionalSuperkoHistory::size() const {
  return entries.size();
}

const PositionalSuperkoKey& PositionalSuperkoHistory::at(size_t index) const {
  return entries.at(index);
}

const PositionalSuperkoKey& PositionalSuperkoHistory::back() const {
  return entries.back();
}

bool PositionalSuperkoHistory::contains(const PositionalSuperkoKey& key) const {
  for(const PositionalSuperkoKey& entry: entries) {
    if(entry == key)
      return true;
  }
  return false;
}

bool PositionalSuperkoHistory::contains(const Board& board) const {
  return contains(PositionalSuperkoKey(board));
}

void PositionalSuperkoHistory::requireMatchingDimensions(const PositionalSuperkoKey& key) const {
  if(entries.empty())
    throw StringError("Positional superko history must retain its initial entry");
  if(key.getXSize() != entries.front().getXSize() || key.getYSize() != entries.front().getYSize())
    throw StringError("Positional superko history cannot mix board dimensions");
}

void PositionalSuperkoHistory::append(const PositionalSuperkoKey& key) {
  requireMatchingDimensions(key);
  entries.push_back(key);
}

void PositionalSuperkoHistory::append(const Board& board) {
  append(PositionalSuperkoKey(board));
}

bool PositionalSuperkoHistory::operator==(const PositionalSuperkoHistory& other) const {
  return entries == other.entries;
}

bool PositionalSuperkoHistory::operator!=(const PositionalSuperkoHistory& other) const {
  return !(*this == other);
}
