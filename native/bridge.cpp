// Original adapter code. Depends on gamerpuppy/sts_lightspeed (MIT).
// Reviewed against public master sources retrieved 2026-09-16.
// The delivery environment cannot fetch/build upstream: compilation and real-game
// differential validation are EXPLICIT downstream gates, not claimed complete.
#include <cctype>
#include <cstdint>
#include <algorithm>
#include <array>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/Action.h"

namespace py = pybind11;
using namespace sts;
using A = sts::search::Action;
using AT = sts::search::ActionType;

static const std::unordered_map<std::string, CardId> allowed_cards = {
    {"STRIKE_RED", CardId::STRIKE_RED}, {"DEFEND_RED", CardId::DEFEND_RED},
    {"BASH", CardId::BASH}, {"ASCENDERS_BANE", CardId::ASCENDERS_BANE},
    {"POMMEL_STRIKE", CardId::POMMEL_STRIKE}, {"SHRUG_IT_OFF", CardId::SHRUG_IT_OFF},
    {"IRON_WAVE", CardId::IRON_WAVE}, {"CLEAVE", CardId::CLEAVE},
    {"UPPERCUT", CardId::UPPERCUT}, {"CARNAGE", CardId::CARNAGE},
    {"TWIN_STRIKE", CardId::TWIN_STRIKE}, {"METALLICIZE", CardId::METALLICIZE},
    {"IMPERVIOUS", CardId::IMPERVIOUS}, {"GHOSTLY_ARMOR", CardId::GHOSTLY_ARMOR},
    {"DISARM", CardId::DISARM}, {"INFLAME", CardId::INFLAME},
    {"HEAVY_BLADE", CardId::HEAVY_BLADE}, {"ANGER", CardId::ANGER},
    {"WHIRLWIND", CardId::WHIRLWIND}, {"THUNDERCLAP", CardId::THUNDERCLAP},
    {"BLUDGEON", CardId::BLUDGEON},
    // Status cards the supported enemies inject into our deck. Slimed is
    // playable (it just exhausts); Dazed is unplayable and ethereal.
    {"SLIMED", CardId::SLIMED}, {"DAZED", CardId::DAZED}
};

static std::string card_name(CardId id) {
    for (const auto &p: allowed_cards) if (p.second == id) return p.first;
    // Name the offender: enemies inject status cards, and a bare refusal makes
    // widening the whitelist a guessing game.
    const auto index = static_cast<std::size_t>(id);
    const std::string upstream = index < std::size(cardEnumStrings) ? cardEnumStrings[index] : "UNKNOWN";
    throw std::runtime_error("Unsupported generated card: " + upstream +
                             "; extend capability tests before widening the whitelist");
}
// Encounters are whitelisted one by one: each needs its visible move set and
// power set covered by tests before it is offered to the trainer.
static const std::unordered_map<std::string, MonsterEncounter> supported_encounters = {
    {"CULTIST", MonsterEncounter::CULTIST}, {"JAW_WORM", MonsterEncounter::JAW_WORM},
    {"TWO_LOUSE", MonsterEncounter::TWO_LOUSE}, {"THREE_LOUSE", MonsterEncounter::THREE_LOUSE},
    {"BLUE_SLAVER", MonsterEncounter::BLUE_SLAVER}, {"RED_SLAVER", MonsterEncounter::RED_SLAVER},
    {"EXORDIUM_THUGS", MonsterEncounter::EXORDIUM_THUGS},
    {"EXORDIUM_WILDLIFE", MonsterEncounter::EXORDIUM_WILDLIFE},
    {"TWO_FUNGI_BEASTS", MonsterEncounter::TWO_FUNGI_BEASTS},
    {"LOOTER", MonsterEncounter::LOOTER}, {"GREMLIN_GANG", MonsterEncounter::GREMLIN_GANG},
    {"SMALL_SLIMES", MonsterEncounter::SMALL_SLIMES}, {"LOTS_OF_SLIMES", MonsterEncounter::LOTS_OF_SLIMES},
    {"LARGE_SLIME", MonsterEncounter::LARGE_SLIME},
    {"GREMLIN_NOB", MonsterEncounter::GREMLIN_NOB}, {"LAGAVULIN", MonsterEncounter::LAGAVULIN},
    {"THREE_SENTRIES", MonsterEncounter::THREE_SENTRIES},
};

static std::vector<std::string> split_csv(const std::string &text) {
    std::vector<std::string> parts;
    for (std::size_t start = 0; start <= text.size();) {
        const auto comma = text.find(',', start);
        const auto end = comma == std::string::npos ? text.size() : comma;
        if (end > start) parts.push_back(text.substr(start, end - start));
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return parts;
}
// Upstream keeps the display names ("Curl Up"); the adapter exposes stable
// tokens so the cross-backend key and the trainer see one spelling.
static std::string status_name(MonsterStatus status) {
    const auto index = static_cast<std::size_t>(status);
    if (index >= std::size(enemyStatusStrings)) return "UNKNOWN";
    std::string out;
    for (char ch : std::string(enemyStatusStrings[index])) {
        if (ch == ' ') out.push_back('_');
        else out.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
    }
    return out;
}
// Internal move id -> the intent class the player actually sees. The move id is
// read here ONLY to compute the class; it is never exported under any name. The
// table is generated from the simulator's own effect composition, with the
// game-checked overrides recorded in scripts/gen_intent_table.py.
static const std::unordered_map<MMID, std::string> public_intents = {
#define PUBLIC_INTENT(name, cls) {MMID::name, #cls},
#include "intent_table.def"
#undef PUBLIC_INTENT
};
static std::string public_intent(MMID move) {
    if (move == MMID::INVALID) return "NONE";
    const auto found = public_intents.find(move);
    if (found == public_intents.end())
        throw std::runtime_error("Move has no audited public intent; extend the mapping before widening the pilot");
    return found->second;
}
static std::string move_name(MMID move) {
    const auto index = static_cast<std::size_t>(move);
    return index < std::size(monsterMoveStrings) ? std::string(monsterMoveStrings[index])
                                                 : std::string("INVALID");
}
static std::string card_type(CardType type) {
    switch(type) {
        case CardType::ATTACK: return "ATTACK";
        case CardType::SKILL: return "SKILL";
        case CardType::POWER: return "POWER";
        case CardType::STATUS: return "STATUS";
        case CardType::CURSE: return "CURSE";
        default: return "UNKNOWN";
    }
}
static py::dict public_card(const CardInstance &c) {
    py::dict d;
    d["id"] = card_name(c.id); d["cost"] = int(c.costForTurn);
    d["upgraded"] = c.getUpgradeCount(); d["type"] = card_type(c.getType());
    d["exhaust"] = c.doesExhaust(); d["ethereal"] = c.isEthereal();
    d["targeted"] = c.requiresTarget(); d["special"] = int(c.specialData);
    d["free"] = c.freeToPlayOnce; d["retain"] = c.retain;
    // uniqueId, raw pointers and the draw-pile position are NEVER exported.
    return d;
}

class PilotBattle {
    BattleContext bc{};
    int potions_used = 0;
    // What the player watched the enemy do. moveHistory[] is a history of ROLLED
    // moves, not of executed ones: a monster that keeps using the same move is
    // never re-rolled, so moveHistory[1] goes stale (a Cultist attacking every
    // turn still reports INCANTATION). Track the move that was current during the
    // last turn we saw instead; that is the one the player watched resolve.
    mutable int seen_turn = -1;
    mutable std::array<MMID, 8> last_planned{};
    mutable std::array<MMID, 8> last_executed{};
public:
    PilotBattle() = default;
    PilotBattle(const PilotBattle&) = default;
    PilotBattle(const py::dict &scenario, std::uint64_t seed) {
        const auto encounter = py::cast<std::string>(scenario["encounter"]);
        const auto encounter_id = supported_encounters.find(encounter);
        if (encounter_id == supported_encounters.end())
            throw std::invalid_argument("Unsupported pilot encounter: " + encounter);
        const int asc = py::cast<int>(scenario["ascension"]);
        if (asc < 0 || asc > 20) throw std::invalid_argument("Invalid ascension");
        GameContext gc(CharacterClass::IRONCLAD, seed, asc);
        gc.curHp = py::cast<int>(scenario["hp"]); gc.maxHp = py::cast<int>(scenario["max_hp"]);
        if (gc.curHp <= 0 || gc.curHp > gc.maxHp) throw std::invalid_argument("Invalid starting HP");
        gc.act = 1; gc.floorNum = 1; gc.curRoom = Room::MONSTER;
        gc.curMapNodeX = -100; gc.curMapNodeY = -100; // no burning-elite marker match
        auto deck = py::cast<std::vector<std::string>>(scenario["deck"]);
        if (deck.empty() || deck.size() > 60) throw std::invalid_argument("Deck size must be 1..60");
        while (gc.deck.size()) gc.deck.remove(gc, gc.deck.size()-1);
        for (auto name: deck) {
            bool upgraded = !name.empty() && name.back() == '+';
            if (upgraded) name.pop_back();
            auto found = allowed_cards.find(name);
            if (found == allowed_cards.end()) throw std::invalid_argument("Unsupported pilot card: " + name);
            if (upgraded && name == "ASCENDERS_BANE") throw std::invalid_argument("Ascenders Bane cannot upgrade");
            Card c(found->second); if (upgraded) c.upgrade();
            gc.deck.obtain(gc, c);
        }
        if (scenario.contains("potions") && py::len(scenario["potions"]) != 0)
            throw std::invalid_argument("Native pilot intentionally excludes potions; do not silently ignore them");
        if (scenario.contains("relics") && py::len(scenario["relics"]) != 0)
            throw std::invalid_argument("Native pilot uses starting Burning Blood only");
        if (scenario.contains("act") && py::cast<int>(scenario["act"]) != 1)
            throw std::invalid_argument("Native pilot supports act 1 only");
        if (scenario.contains("floor") && py::cast<int>(scenario["floor"]) != 1)
            throw std::invalid_argument("Native pilot uses floor 1 fixtures only");
        bc.player.cc = CharacterClass::IRONCLAD;
        bc.init(gc, encounter_id->second);
        check_supported_state();
    }
    void check_supported_state() const {
        if (bc.undefinedBehaviorEvoked) throw std::runtime_error("Upstream flagged undefined behavior");
        if (bc.outcome == Outcome::UNDECIDED && bc.inputState != InputState::PLAYER_NORMAL)
            throw std::runtime_error("Unsupported pilot input state; no automatic choose/end fallback");
    }
    std::vector<A> actions() const {
        std::vector<A> out;
        if (bc.outcome != Outcome::UNDECIDED) return out;
        check_supported_state();
        for (int i=0; i<bc.cards.cardsInHand; ++i) {
            const auto &c=bc.cards.hand[i];
            if (c.requiresTarget()) {
                for (int j=0; j<bc.monsters.monsterCount; ++j) {
                    A a(AT::CARD,i,j);
                    if (bc.monsters.arr[j].isTargetable() && a.isValidAction(bc)) out.push_back(a);
                }
            } else {
                A a(AT::CARD,i,0); if (a.isValidAction(bc)) out.push_back(a);
            }
        }
        A end(AT::END_TURN); if (end.isValidAction(bc)) out.push_back(end);
        if (out.empty()) throw std::runtime_error("No legal actions for a live pilot state");
        return out;
    }
    py::dict observe() const {
        check_supported_state();
        if (bc.turn != seen_turn) {
            for (int i=0; i<bc.monsters.monsterCount && i<int(last_planned.size()); ++i) {
                if (seen_turn >= 0) last_executed[i] = last_planned[i];
                last_planned[i] = bc.monsters.arr[i].moveHistory[0];
            }
            seen_turn = bc.turn;
        }
        py::dict o,p; py::list enemies,hand,draw,discard,exhaust,acts,powers,relics;
        // Must match stsai.util.SCHEMA_VERSION; validate_public rejects a mismatch.
        o["schema_version"]=3; o["backend"]="lightspeed_pilot";
        o["turn"]=bc.turn; o["phase"]="PLAYER_NORMAL"; o["ascension"]=bc.ascension;
        p["hp"]=bc.player.curHp; p["max_hp"]=bc.player.maxHp;
        p["block"]=bc.player.block; p["energy"]=bc.player.energy;
        p["strength"]=bc.player.strength; p["dexterity"]=bc.player.dexterity;
        p["artifact"]=bc.player.artifact;
        p["weak"]=bc.player.getStatus<PlayerStatus::WEAK>();
        p["vulnerable"]=bc.player.getStatus<PlayerStatus::VULNERABLE>();
        p["frail"]=bc.player.getStatus<PlayerStatus::FRAIL>();
        p["metallicize"]=bc.player.getStatus<PlayerStatus::METALLICIZE>();
        p["cards_played"]=int(bc.player.cardsPlayedThisTurn);
        p["attacks_played"]=int(bc.player.attacksPlayedThisTurn);
        p["skills_played"]=int(bc.player.skillsPlayedThisTurn);
        o["player"]=p;
        for (int i=0;i<bc.monsters.monsterCount;++i) {
            const auto &m=bc.monsters.arr[i]; py::dict e;
            e["id"]=std::string(m.getName()); e["slot"]=i; e["hp"]=m.curHp; e["max_hp"]=m.maxHp;
            e["block"]=m.block; e["strength"]=m.strength; e["weak"]=m.weak; e["vulnerable"]=m.vulnerable;
            e["artifact"]=int(m.artifact); e["half_dead"]=m.halfDead;
            if (m.isAttacking() && m.isTargetable()) {
                const auto damage=m.getMoveBaseDamage(bc);
                e["intent_damage"]=m.calculateDamageToPlayer(bc,damage.damage);
                e["hits"]=damage.attackCount;
            } else { e["intent_damage"]=0; e["hits"]=0; }
            // The class the player sees, computed from the held move. Two moves
            // that show the same class are indistinguishable to the player and
            // are deliberately NOT separated here; the identity never leaves this
            // function.
            e["intent"]=public_intent(m.moveHistory[0]);
            MMID executed = (seen_turn > 0 && i < int(last_executed.size()))
                            ? last_executed[i] : MMID::INVALID;
            // A battle can end on the enemy's own action -- a Looter escaping
            // never gets a next turn -- and the player still watched that move.
            // A dead enemy may have been killed before it acted, so only a
            // surviving one confirms the move it was holding.
            if (bc.outcome != Outcome::UNDECIDED && m.curHp > 0 && i < int(last_planned.size()))
                executed = last_planned[i];
            // The executed move is reported as its PUBLIC class too: the player
            // watched it resolve, but its identity is still not exported.
            e["previous_intent"]=public_intent(executed);
            // Never expose miscInfo, stored future damage rolls, hidden seeds,
            // or latent enemy plans.
            enemies.append(e);
            // Every non-zero status is a visible power icon in game, so exporting
            // the whole runtime set is both fair and the only way to avoid
            // silently hiding a new enemy's key mechanic.
            for (int s=0; s<int(MonsterStatus::INVALID); ++s) {
                const auto status=static_cast<MonsterStatus>(s);
                const int amount=m.getStatusInternal(status);
                if (!amount) continue;
                py::dict pw; pw["id"]=status_name(status); pw["owner"]=i; pw["amount"]=amount;
                powers.append(pw);
            }
        }
        for(int i=0;i<bc.cards.cardsInHand;++i) hand.append(public_card(bc.cards.hand[i]));
        // Sorting is repeated in Python by the exact cross-backend canonical key.
        auto cards=std::vector<CardInstance>(bc.cards.drawPile.begin(),bc.cards.drawPile.end());
        std::sort(cards.begin(),cards.end(),[](const CardInstance &a,const CardInstance &b) {
            return std::make_tuple(card_name(a.id),a.upgraded,int(a.costForTurn),a.specialData,a.freeToPlayOnce,a.retain)
                 < std::make_tuple(card_name(b.id),b.upgraded,int(b.costForTurn),b.specialData,b.freeToPlayOnce,b.retain);
        });
        for(const auto &c:cards) draw.append(public_card(c));
        for(const auto &c:bc.cards.discardPile) discard.append(public_card(c));
        for(const auto &c:bc.cards.exhaustPile) exhaust.append(public_card(c));
        for(const auto &a:actions()) {
            py::dict d; d["id"]=std::to_string(a.bits); d["selection"]=py::list();
            if(a.getActionType()==AT::END_TURN) {
                d["kind"]="end"; d["source"]=-1; d["target"]=-1; d["source_zone"]="none"; d["card_id"]="END"; d["cost"]=0;
            } else {
                const auto &c=bc.cards.hand[a.getSourceIdx()]; d["kind"]="play";
                d["source"]=a.getSourceIdx(); d["source_zone"]="hand";
                d["target"]=c.requiresTarget()?a.getTargetIdx():-1;
                d["card_id"]=card_name(c.id); d["cost"]=c.isXCost()?bc.player.energy:int(c.costForTurn);
            }
            acts.append(d);
        }
        py::dict r; r["id"]="BURNING_BLOOD"; r["counter"]=-1; relics.append(r);
        o["enemies"]=enemies; o["hand"]=hand; o["draw_pile"]=draw;
        o["discard_pile"]=discard; o["exhaust_pile"]=exhaust;
        o["known_top"]=py::list(); o["choices"]=py::list();
        o["powers"]=powers; o["relics"]=relics; o["potions"]=py::list(); o["potions_used"]=potions_used;
        o["terminal"]=bc.outcome!=Outcome::UNDECIDED; o["won"]=bc.outcome==Outcome::PLAYER_VICTORY;
        o["actions"]=acts; return o;
    }
    py::dict step(const std::string &action_id) {
        const auto legal=actions(); auto found=std::find_if(legal.begin(),legal.end(),[&](const A &a){return std::to_string(a.bits)==action_id;});
        if(found==legal.end()) throw std::invalid_argument("Illegal or stale native action");
        found->execute(bc); check_supported_state(); return observe();
    }
    // TEST-ONLY introspection for the coverage tests. This deliberately returns
    // internal move names, which observe() never does: the coverage suite has to
    // prove every branch of every supported monster is reachable, and the public
    // intent class cannot separate two moves that share a class. Nothing here
    // may reach the trainer, the search or any policy interface -- tests assert
    // that observe() exposes none of these keys.
    py::dict debug_internals() const {
        check_supported_state();
        py::dict out; py::list moves, classes; py::dict executed;
        for (int i=0; i<bc.monsters.monsterCount; ++i) {
            const auto &m=bc.monsters.arr[i];
            moves.append(move_name(m.moveHistory[0]));
            classes.append(public_intent(m.moveHistory[0]));
            MMID done = (seen_turn > 0 && i < int(last_executed.size()))
                        ? last_executed[i] : MMID::INVALID;
            // mirror observe(): a surviving enemy at a decided battle has acted
            if (bc.outcome != Outcome::UNDECIDED && m.curHp > 0 && i < int(last_planned.size()))
                done = last_planned[i];
            executed[py::int_(i)] = move_name(done);
        }
        out["held_moves"]=moves; out["held_classes"]=classes; out["executed_moves"]=executed;
        out["warning"]="test-only; never exported by observe() and never a training input";
        return out;
    }
    std::unique_ptr<PilotBattle> sample(std::uint64_t sampler_seed) const {
        check_supported_state();
        auto result=std::make_unique<PilotBattle>(*this);
        std::mt19937_64 rng(sampler_seed);
        // Independent future RNG approximation, NOT the exact posterior of
        // original STS's correlated seeded streams. No original RNG is reused.
        result->bc.aiRng=Random(rng()); result->bc.cardRandomRng=Random(rng());
        result->bc.miscRng=Random(rng()); result->bc.monsterHpRng=Random(rng());
        result->bc.potionRng=Random(rng()); result->bc.shuffleRng=Random(rng());
        result->bc.seed=0; // debug-only field; never an agent input
        auto &draw=result->bc.cards.drawPile;
        // Canonicalize before shuffling: sampling must not depend on real order.
        std::sort(draw.begin(),draw.end(),[](const CardInstance &a,const CardInstance &b) {
            return std::make_tuple(card_name(a.id),a.upgraded,int(a.costForTurn),a.specialData,a.freeToPlayOnce,a.retain)
                 < std::make_tuple(card_name(b.id),b.upgraded,int(b.costForTurn),b.specialData,b.freeToPlayOnce,b.retain);
        });
        std::shuffle(draw.begin(),draw.end(),rng);
        return result;
    }
};
PYBIND11_MODULE(_lightspeed,m) {
    py::class_<PilotBattle>(m,"PilotBattle")
        .def(py::init<const py::dict&,std::uint64_t>())
        .def("observe",&PilotBattle::observe)
        .def("step",&PilotBattle::step)
        .def("sample",&PilotBattle::sample)
        .def("debug_internals",&PilotBattle::debug_internals);
    m.def("build_info",[](){py::dict d; d["revision"]=STSAI_ENGINE_REVISION;
        // Local rule patches applied on top of `revision`; empty means the tree
        // is byte-for-byte upstream. Tests assert against these hashes.
        const std::string patches=STSAI_ENGINE_PATCHES;
        d["patches"]=split_csv(patches);
        d["backend"]="lightspeed_pilot"; d["belief_model"]="independent_rng_approximation";
        d["game_differential_verified"]=false; return d;});
}
