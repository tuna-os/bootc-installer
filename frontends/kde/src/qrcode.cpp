#include "qrcode.h"

#include <cstdint>

namespace qrcode
{

namespace
{
// Total data codewords and the ECC block layout at EC level M, versions
// 1-6: (blocks, data codewords per block, ec codewords per block). Every
// version here splits evenly, so there is a single block group.
struct Layout {
    int blocks;
    int dataPerBlock;
    int ecPerBlock;
};
constexpr Layout kLayouts[] = {
    {}, // 1-based
    {1, 16, 10}, // V1: 26 total
    {1, 28, 16}, // V2: 44 total
    {1, 44, 26}, // V3: 70 total
    {2, 32, 18}, // V4: 100 total
    {2, 43, 24}, // V5: 134 total
    {4, 27, 16}, // V6: 172 total
};
constexpr int kMaxVersion = 6;

// --- Galois field ----------------------------------------------------------
uint8_t gfMul(uint8_t a, uint8_t b)
{
    uint8_t out = 0;
    for (int i = 0; i < 8; i++) {
        if (b & 1)
            out ^= a;
        const bool hi = (a & 0x80) != 0;
        a <<= 1;
        if (hi)
            a ^= 0x1D; // x^8 + x^4 + x^3 + x^2 + 1
        b >>= 1;
    }
    return out;
}

uint8_t gfPow(uint8_t base, int exp)
{
    uint8_t out = 1;
    for (int i = 0; i < exp; i++)
        out = gfMul(out, base);
    return out;
}

// The remainder of data divided by the generator polynomial of `ecLength`
// terms: the ec codewords of one block.
std::vector<uint8_t> ecc(const std::vector<uint8_t> &data, int ecLength)
{
    // Generator: (x - a^0)(x - a^1)... with a = 2.
    std::vector<uint8_t> generator{1};
    for (int i = 0; i < ecLength; i++) {
        std::vector<uint8_t> next(generator.size() + 1, 0);
        for (size_t j = 0; j < generator.size(); j++) {
            next[j] ^= generator[j];
            next[j + 1] ^= gfMul(generator[j], gfPow(2, i));
        }
        generator = next;
    }
    std::vector<uint8_t> remainder(data.size() + ecLength, 0);
    for (size_t i = 0; i < data.size(); i++)
        remainder[i] = data[i];
    for (size_t i = 0; i < data.size(); i++) {
        const uint8_t factor = remainder[i];
        if (factor == 0)
            continue;
        for (size_t j = 0; j < generator.size(); j++)
            remainder[i + j] ^= gfMul(generator[j], factor);
    }
    return std::vector<uint8_t>(remainder.end() - ecLength, remainder.end());
}

// --- Bit writer ------------------------------------------------------------
struct Bits {
    std::vector<uint8_t> bytes;
    int bitLength = 0;
    void append(int value, int bits)
    {
        for (int i = bits - 1; i >= 0; i--) {
            if (bitLength % 8 == 0)
                bytes.push_back(0);
            if (value & (1 << i))
                bytes.back() |= uint8_t(1 << (7 - (bitLength % 8)));
            bitLength++;
        }
    }
};

// --- Matrix ----------------------------------------------------------------
struct Matrix {
    int size = 0;
    std::vector<char> dark; // -1 unset, 0 light, 1 dark
    std::vector<char> function; // 1 for a finder/timing/etc module
    Matrix() = default;
    explicit Matrix(int version)
        : size(17 + 4 * version)
        , dark(size_t(size) * size_t(size), -1)
        , function(size_t(size) * size_t(size), 0)
    {
    }
    char at(int x, int y) const { return dark[size_t(y) * size_t(size) + size_t(x)]; }
    void set(int x, int y, bool isDark, bool isFunction)
    {
        dark[size_t(y) * size_t(size) + size_t(x)] = isDark ? 1 : 0;
        if (isFunction)
            function[size_t(y) * size_t(size) + size_t(x)] = 1;
    }
    bool isFunction(int x, int y) const { return function[size_t(y) * size_t(size) + size_t(x)] != 0; }
};

void finder(Matrix &m, int ox, int oy)
{
    for (int dy = -1; dy <= 7; dy++) {
        for (int dx = -1; dx <= 7; dx++) {
            const int x = ox + dx;
            const int y = oy + dy;
            if (x < 0 || y < 0 || x >= m.size || y >= m.size)
                continue;
            const bool edge = dx == -1 || dx == 7 || dy == -1 || dy == 7;
            const bool core = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6
                && (dx == 0 || dx == 6 || dy == 0 || dy == 6 || (dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4));
            m.set(x, y, core && !edge, true);
        }
    }
}

void alignment(Matrix &m, int cx, int cy)
{
    for (int dy = -2; dy <= 2; dy++) {
        for (int dx = -2; dx <= 2; dx++)
            m.set(cx + dx, cy + dy, dx == -2 || dx == 2 || dy == -2 || dy == 2 || (dx == 0 && dy == 0), true);
    }
}

void drawFunctions(Matrix &m, int version)
{
    finder(m, 0, 0);
    finder(m, m.size - 7, 0);
    finder(m, 0, m.size - 7);
    for (int i = 8; i < m.size - 8; i++) {
        m.set(i, 6, i % 2 == 0, true);
        m.set(6, i, i % 2 == 0, true);
    }
    if (version >= 2) {
        const int last = 4 * version + 10; // alignment centre for V2-6
        for (int x : {6, last}) {
            for (int y : {6, last}) {
                // The three finders own their corners' patterns.
                if ((x == 6 && y == 6) || (x == last && y == 6) || (x == 6 && y == last))
                    continue;
                alignment(m, x, y);
            }
        }
    }
    // The dark module and the format info area reservation. The first copy
    // sits at column 7 rows 0-5, (8,7), (8,8), (7,8) and row 8 columns 0-5;
    // the second at row 8 columns size-1 down to size-8 and column 8 rows
    // size-1 down to size-7. Every other module stays data.
    m.set(8, 4 * version + 9, true, true);
    for (int i = 0; i <= 5; i++) {
        if (m.at(i, 8) < 0)
            m.set(i, 8, false, true);
        if (m.at(8, i) < 0)
            m.set(8, i, false, true);
    }
    if (m.at(7, 8) < 0)
        m.set(7, 8, false, true);
    if (m.at(8, 8) < 0)
        m.set(8, 8, false, true);
    if (m.at(8, 7) < 0)
        m.set(8, 7, false, true);
    for (int i = 0; i < 8; i++) {
        if (m.at(m.size - 1 - i, 8) < 0)
            m.set(m.size - 1 - i, 8, false, true);
    }
    for (int i = 0; i < 7; i++) {
        if (m.at(8, m.size - 1 - i) < 0)
            m.set(8, m.size - 1 - i, false, true);
    }
}

// Format information: 15 BCH bits over (ec level, mask), drawn twice.
int formatBits(int mask)
{
    int data = (0 << 3) | mask; // EC level M is 00
    int rem = data;
    for (int i = 0; i < 10; i++)
        rem = (rem << 1) ^ ((rem >> 9) * 0x537);
    return ((data << 10) | rem) ^ 0x5412;
}

void drawFormat(Matrix &m, int mask)
{
    const int bits = formatBits(mask);
    auto bit = [&](int i) { return (bits >> i) & 1; };
    // First copy, wrapping the top-left finder: bits 14-9 along row 8,
    // bit 8 at (7,8), bit 7 at (8,8), bit 6 at (8,7), bits 5-0 up column 8.
    for (int i = 0; i <= 5; i++)
        m.set(i, 8, bit(14 - i), true);
    m.set(7, 8, bit(8), true);
    m.set(8, 8, bit(7), true);
    m.set(8, 7, bit(6), true);
    for (int y = 0; y <= 5; y++)
        m.set(8, y, bit(y), true);
    // Second copy: bits 0-7 along row 8 from the right edge, bits 14-8
    // down column 8 from the bottom edge.
    for (int i = 0; i < 8; i++)
        m.set(m.size - 1 - i, 8, bit(i), true);
    for (int i = 0; i < 7; i++)
        m.set(8, m.size - 1 - i, bit(14 - i), true);
}

// --- Data placement --------------------------------------------------------
bool maskApplies(int mask, int x, int y)
{
    switch (mask) {
    case 0: return (x + y) % 2 == 0;
    case 1: return y % 2 == 0;
    case 2: return x % 3 == 0;
    case 3: return (x + y) % 3 == 0;
    case 4: return (y / 2 + x / 3) % 2 == 0;
    case 5: return (x * y) % 2 + (x * y) % 3 == 0;
    case 6: return ((x * y) % 2 + (x * y) % 3) % 2 == 0;
    default: return ((x + y) % 2 + (x * y) % 3) % 2 == 0;
    }
}

// --- Data placement --------------------------------------------------------
void placeData(Matrix &m, const std::vector<uint8_t> &codewords)
{
    size_t bit = 0;
    const size_t total = codewords.size() * 8;
    for (int right = m.size - 1; right >= 1; right -= 2) {
        if (right == 6)
            right = 5; // skip the vertical timing column
        const bool upward = ((right + 1) & 2) == 0;
        for (int line = 0; line < m.size; line++) {
            const int y = upward ? m.size - 1 - line : line;
            for (int j = 0; j < 2; j++) {
                const int x = right - j;
                if (!m.isFunction(x, y) && m.at(x, y) < 0) {
                    const bool dark = bit < total && (codewords[bit / 8] & (0x80 >> (bit % 8)));
                    m.set(x, y, dark, false);
                    bit++;
                }
            }
        }
    }
}

// --- Penalty ---------------------------------------------------------------
int penalty(const Matrix &m)
{
    // The ISO evaluation as segno implements it (the golden generator):
    // N1 runs, N2 blocks, N3 the 1:1:3:1:1 pattern with light around it,
    // N4 the dark proportion. Scores run on the matrix WITHOUT format
    // info; the caller draws that after picking the mask.
    const int n = m.size;
    auto dark = [&](int x, int y) { return m.at(x, y) != 0; };
    int score = 0;
    int darkCount = 0;
    for (int y = 0; y < n; y++) {
        for (int x = 0; x < n; x++) {
            if (dark(x, y))
                darkCount++;
        }
    }
    // N3 in one line: 1011101 at an edge, or with four light modules
    // before or after it (segno's n3_pattern_occurrences).
    auto n3 = [&](const std::vector<char> &line) {
        int count = 0;
        const int len = int(line.size());
        static const int pattern[7] = {1, 0, 1, 1, 1, 0, 1};
        int idx = 0;
        while (idx + 7 <= len) {
            bool match = true;
            for (int i = 0; i < 7; i++) {
                if ((line[size_t(idx + i)] != 0) != (pattern[i] != 0)) {
                    match = false;
                    break;
                }
            }
            if (!match) {
                idx++;
                continue;
            }
            bool ok = idx == 0 || idx == len - 7;
            if (!ok) {
                bool beforeLight = true;
                for (int i = idx - 4 < 0 ? 0 : idx - 4; i < idx; i++) {
                    if (line[size_t(i)] != 0)
                        beforeLight = false;
                }
                bool afterLight = true;
                const int afterEnd = idx + 11 < len ? idx + 11 : len;
                for (int i = idx + 7; i < afterEnd; i++) {
                    if (line[size_t(i)] != 0)
                        afterLight = false;
                }
                ok = beforeLight || afterLight;
            }
            if (ok) {
                count += 40;
                idx += 7;
            } else {
                idx += 4;
            }
        }
        return count;
    };
    for (int y = 0; y < n; y++) {
        std::vector<char> row(size_t(n), 0);
        for (int x = 0; x < n; x++)
            row[size_t(x)] = dark(x, y) ? 1 : 0;
        score += n3(row);
    }
    for (int x = 0; x < n; x++) {
        std::vector<char> col(size_t(n), 0);
        for (int y = 0; y < n; y++)
            col[size_t(y)] = dark(x, y) ? 1 : 0;
        score += n3(col);
    }
    // N1: a run of five or more scores its length minus two.
    for (int y = 0; y < n; y++) {
        int run = 1;
        for (int x = 1; x <= n; x++) {
            if (x < n && dark(x, y) == dark(x - 1, y)) {
                run++;
            } else {
                if (run >= 5)
                    score += run - 2;
                run = 1;
            }
        }
    }
    for (int x = 0; x < n; x++) {
        int run = 1;
        for (int y = 1; y <= n; y++) {
            if (y < n && dark(x, y) == dark(x, y - 1)) {
                run++;
            } else {
                if (run >= 5)
                    score += run - 2;
                run = 1;
            }
        }
    }
    // N2: every 2x2 block of one colour.
    for (int y = 0; y < n - 1; y++) {
        for (int x = 0; x < n - 1; x++) {
            const bool d = dark(x, y);
            if (dark(x + 1, y) == d && dark(x, y + 1) == d && dark(x + 1, y + 1) == d)
                score += 3;
        }
    }
    // N4: ten points per full five percent away from half dark.
    const int total = n * n;
    score += 10 * (std::abs(darkCount * 100 - 50 * total) / (5 * total));
    return score;
}

void applyMask(Matrix &m, int mask)
{
    for (int y = 0; y < m.size; y++) {
        for (int x = 0; x < m.size; x++) {
            if (!m.isFunction(x, y) && maskApplies(mask, x, y))
                m.set(x, y, !m.at(x, y), false);
        }
    }
}

} // namespace

Code encode(const QString &text)
{
    Code code;
    const QByteArray bytes = text.toUtf8();
    // Mode indicator (0100) + character count + data + terminator.
    int version = 0;
    for (int v = 1; v <= kMaxVersion; v++) {
        const int countBits = v <= 9 ? 8 : 16;
        const int bits = 4 + countBits + int(bytes.size()) * 8;
        // Terminator (up to 4), then the pad byte segno's goldens carry
        // even when the stream is already byte-aligned.
        const int codewords = (bits + 4 + 8) / 8;
        if (codewords <= kLayouts[v].blocks * kLayouts[v].dataPerBlock) {
            version = v;
            break;
        }
    }
    if (version == 0)
        return code;
    const Layout layout = kLayouts[version];
    const int countBits = version <= 9 ? 8 : 16;
    const int totalData = layout.blocks * layout.dataPerBlock;

    Bits bits;
    bits.append(0b0100, 4);
    bits.append(int(bytes.size()), countBits);
    for (char byte : bytes)
        bits.append(uint8_t(byte), 8);
    const int capacity = totalData * 8;
    int terminator = capacity - bits.bitLength;
    if (terminator > 4)
        terminator = 4;
    bits.append(0, terminator);
    // segno (the golden generator) appends a full zero byte when the stream
    // is already byte-aligned, not zero bits. Decoders ignore pad content,
    // so matching it costs nothing and keeps the goldens exact.
    bits.append(0, 8 - (bits.bitLength % 8));
    for (uint8_t pad = 0xEC; int(bits.bytes.size()) < totalData; pad ^= 0xEC ^ 0x11)
        bits.bytes.push_back(pad);

    // Split into blocks, add ECC, interleave.
    std::vector<uint8_t> codewords;
    std::vector<std::vector<uint8_t>> blocks;
    std::vector<std::vector<uint8_t>> eccBlocks;
    for (int b = 0; b < layout.blocks; b++) {
        std::vector<uint8_t> block(bits.bytes.begin() + b * layout.dataPerBlock,
                                   bits.bytes.begin() + (b + 1) * layout.dataPerBlock);
        blocks.push_back(block);
        eccBlocks.push_back(ecc(block, layout.ecPerBlock));
    }
    for (int i = 0; i < layout.dataPerBlock; i++) {
        for (int b = 0; b < layout.blocks; b++)
            codewords.push_back(blocks[size_t(b)][size_t(i)]);
    }
    for (int i = 0; i < layout.ecPerBlock; i++) {
        for (int b = 0; b < layout.blocks; b++)
            codewords.push_back(eccBlocks[size_t(b)][size_t(i)]);
    }

    Matrix base(version);
    drawFunctions(base, version);
    placeData(base, codewords);

    int bestMask = 0;
    int bestScore = -1;
    Matrix best = base;
    for (int mask = 0; mask < 8; mask++) {
        Matrix trial = base;
        applyMask(trial, mask);
        // No format info yet: segno scores the masked data first and draws
        // the format bits of the winner afterwards.
        const int score = penalty(trial);
        if (bestScore < 0 || score < bestScore) {
            bestScore = score;
            bestMask = mask;
            best = trial;
        }
    }
    drawFormat(best, bestMask);

    code.ok = true;
    code.version = version;
    code.size = base.size;
    code.modules = best.dark;
    return code;
}

QStringList Code::rows() const
{
    QStringList out;
    for (int y = 0; y < size; y++) {
        QString row;
        row.reserve(size);
        for (int x = 0; x < size; x++)
            row.append(at(x, y) ? QLatin1Char('1') : QLatin1Char('0'));
        out.append(row);
    }
    return out;
}

} // namespace qrcode
