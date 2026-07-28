#include "../game/positionalsuperko.h"

using namespace std;

PositionalSuperkoKey::PositionalSuperkoKey(const Board& board)
  : xSize(board.x_size), ySize(board.y_size), occupancy()
{
  occupancy.reserve(static_cast<size_t>(xSize * ySize));
  for(int y = 0; y < ySize; y++) {
    for(int x = 0; x < xSize; x++) {
      Loc loc = Location::getLoc(x,y,xSize);
      Color color = board.colors[loc];
      if(color != C_EMPTY && color != C_BLACK && color != C_WHITE)
        throw StringError("Positional superko key requires playable occupancy");
      occupancy.push_back(static_cast<uint8_t>(color));
    }
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

void PositionalSuperkoHistory::append(const PositionalSuperkoKey& key) {
  entries.push_back(key);
}

void PositionalSuperkoHistory::append(const Board& board) {
  entries.emplace_back(board);
}

bool PositionalSuperkoHistory::operator==(const PositionalSuperkoHistory& other) const {
  return entries == other.entries;
}

bool PositionalSuperkoHistory::operator!=(const PositionalSuperkoHistory& other) const {
  return !(*this == other);
}
