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
// Which monsters have a construction-time hidden attack base, and the public
// range it is drawn from. Mirrors Monster.cpp::construct:118-120 (louse, 6-8 at
// A>=2 and 5-7 below) and :126-128 (darkling, not reachable in the pilot).
static bool hidden_attack_base(MonsterId id, int ascension, int &low, int &high) {
    if (id == MonsterId::GREEN_LOUSE || id == MonsterId::RED_LOUSE) {
        if (ascension >= 2) { low = 6; high = 8; } else { low = 5; high = 7; }
        return true;
    }
    return false;
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
    // What the player watched the enemy do, taken from the engine's own
    // observability event log rather than inferred from a turn counter.
    // moveHistory[] cannot be used for this: it is a history of ROLLED moves, so
    // a monster that keeps using one move is never re-rolled and moveHistory[1]
    // goes stale (a Cultist attacking every turn still reported INCANTATION).
    mutable int consumed_events = 0;
    mutable std::array<MMID, 8> last_executed{};
    // Some monsters have a base attack value rolled at construction and stored
    // in miscInfo (louse BITEs, MonsterSpecific.cpp:745/:1006). Until the enemy
    // shows an attack, the player cannot see it. This keeps, per slot, only the
    // candidates CONSISTENT WITH PUBLIC HISTORY, so a belief sample never reads
    // the true hidden value. `determined` means public history pins it exactly.
    struct PublicBase {
        bool applicable = false;
        int low = 0;
        int high = 0;
    };
    mutable std::array<PublicBase, 8> public_base{};
    mutable std::array<bool, 8> base_initialised{};
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
        // Consume the engine's event log. Only a monster that actually took its
        // turn produces an execute event, so a monster killed before acting, or
        // one that never got a turn because the battle ended, stays untouched.
        // Repeated observe() calls process nothing new, so observations are
        // idempotent by construction.
        for (int e=consumed_events; e<bc.combatEventCount; ++e) {
            const auto &ev=bc.combatEvents[e];
            if (ev.slot<0 || ev.slot>=int(last_executed.size())) continue;
            if (ev.kind==BattleContext::EVENT_EXECUTED) {
                last_executed[ev.slot]=static_cast<MMID>(ev.move);
            } else if (ev.kind==BattleContext::EVENT_SPAWNED) {
                // A new entity occupies the slot: it inherits neither the previous
                // occupant's execution history nor its public memory of a hidden
                // attack base.
                last_executed[ev.slot]=MMID::INVALID;
                base_initialised[ev.slot]=false;
            }
        }
        if (bc.combatEventCount>=BattleContext::EVENT_CAPACITY)
            throw std::runtime_error("Combat event log overflowed; the adapter refuses to guess");
        consumed_events=bc.combatEventCount;

        // Public memory of any construction-time hidden attack base. Only ever
        // narrowed by a damage number the player was actually shown.
        for (int i=0; i<bc.monsters.monsterCount && i<int(public_base.size()); ++i) {
            const auto &m=bc.monsters.arr[i];
            int low=0, high=0;
            const bool applies=hidden_attack_base(m.id, bc.ascension, low, high);
            if (!base_initialised[i]) {
                base_initialised[i]=true;
                public_base[i].applicable=applies;
                public_base[i].low=low; public_base[i].high=high;
            } else if (applies && !public_base[i].applicable) {
                public_base[i].applicable=true; public_base[i].low=low; public_base[i].high=high;
            }
            if (!applies || !m.isAttacking() || !m.isTargetable()) continue;
            // The displayed number is public, so every candidate that reproduces
            // it stays; rounding or a zeroed hit may leave several.
            const int shown=m.calculateDamageToPlayer(bc, m.getMoveBaseDamage(bc).damage);
            int keepLow=-1, keepHigh=-1;
            for (int b=public_base[i].low; b<=public_base[i].high; ++b) {
                if (m.calculateDamageToPlayer(bc, b)!=shown) continue;
                if (keepLow<0) keepLow=b;
                keepHigh=b;
            }
            if (keepLow>=0) { public_base[i].low=keepLow; public_base[i].high=keepHigh; }
        }
        py::dict o,p; py::list enemies,hand,draw,discard,exhaust,acts,powers,relics;
        // Must match stsai.util.SCHEMA_VERSION; validate_public rejects a mismatch.
        o["schema_version"]=4; o["backend"]="lightspeed_pilot";
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
            // Straight from the event log: nothing is inferred from the turn
            // counter, so a Looter escaping still counts (it did take its turn)
            // and a monster killed before acting still reports NONE.
            e["previous_intent"]=public_intent(i<int(last_executed.size()) ? last_executed[i]
                                                                          : MMID::INVALID);
            // Minimal public-derived memory: the range of base attack values the
            // player's own observations still allow. -1 means the monster has no
            // hidden base. Equal bounds mean public history pinned it down.
            e["attack_base_low"]=public_base[i].applicable?public_base[i].low:-1;
            e["attack_base_high"]=public_base[i].applicable?public_base[i].high:-1;
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
        py::dict out; py::list moves, classes; py::dict executed, true_bases, public_bases;
        for (int i=0; i<bc.monsters.monsterCount; ++i) {
            const auto &m=bc.monsters.arr[i];
            moves.append(move_name(m.moveHistory[0]));
            classes.append(public_intent(m.moveHistory[0]));
            executed[py::int_(i)] = move_name(i<int(last_executed.size()) ? last_executed[i]
                                                                          : MMID::INVALID);
            true_bases[py::int_(i)] = int(m.miscInfo);
            py::dict pub; pub["applicable"]=public_base[i].applicable;
            pub["low"]=public_base[i].low; pub["high"]=public_base[i].high;
            public_bases[py::int_(i)] = pub;
        }
        // The independent oracle the lifecycle tests assert against: the engine's
        // own execution/spawn events, in order, exactly as recorded.
        py::list events;
        for (int e=0; e<bc.combatEventCount; ++e) {
            const auto &ev=bc.combatEvents[e]; py::dict d;
            // A spawn event carries a MonsterId, an execute event carries a
            // MonsterMoveId. Two different enums; naming one with the other's
            // table silently invents a move that never happened.
            const bool executed=ev.kind==BattleContext::EVENT_EXECUTED;
            d["kind"]=executed ? "EXECUTED" : "SPAWNED";
            d["slot"]=int(ev.slot);
            if (executed) {
                d["move"]=move_name(static_cast<MMID>(ev.move));
            } else {
                const auto index=static_cast<std::size_t>(static_cast<std::uint16_t>(ev.move));
                d["move"]=index<std::size(monsterIdStrings) ? std::string(monsterIdStrings[index])
                                                            : std::string("UNKNOWN");
            }
            events.append(d);
        }
        out["events"]=events;
        out["held_moves"]=moves; out["held_classes"]=classes; out["executed_moves"]=executed;
        out["true_attack_bases"]=true_bases;
        out["public_attack_base"]=public_bases;
        out["warning"]="test-only; never exported by observe() and never a training input";
        return out;
    }
    // TEST-ONLY: force a monster's construction-time hidden base, so a test can
    // build two roots with the same public history and different hidden values.
    void debug_set_attack_base(int slot, int value) {
        if (slot < 0 || slot >= bc.monsters.monsterCount)
            throw std::invalid_argument("slot out of range");
        bc.monsters.arr[slot].miscInfo = value;
    }
    // TEST-ONLY negative control: the PRE-FIX sampler, which copied the hidden
    // base verbatim. Kept so the counterfactual can demonstrate the dependency
    // it used to leak, without needing the old binary.
    std::unique_ptr<PilotBattle> debug_sample_with_true_base(std::uint64_t sampler_seed) const {
        check_supported_state();
        auto result=std::make_unique<PilotBattle>(*this);
        std::mt19937_64 rng(sampler_seed);
        result->bc.aiRng=Random(rng()); result->bc.cardRandomRng=Random(rng());
        result->bc.miscRng=Random(rng()); result->bc.monsterHpRng=Random(rng());
        result->bc.potionRng=Random(rng()); result->bc.shuffleRng=Random(rng());
        auto &draw=result->bc.cards.drawPile;
        std::sort(draw.begin(),draw.end(),[](const CardInstance &a,const CardInstance &b) {
            return std::make_tuple(card_name(a.id),a.upgraded,int(a.costForTurn),a.specialData,a.freeToPlayOnce,a.retain)
                 < std::make_tuple(card_name(b.id),b.upgraded,int(b.costForTurn),b.specialData,b.freeToPlayOnce,b.retain);
        });
        std::shuffle(draw.begin(),draw.end(),rng);
        return result;   // miscInfo deliberately NOT replaced
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
        // Any construction-time hidden attack base is replaced by something the
        // player's own history allows: the exact value when public observations
        // pinned it, otherwise ONE draw from the candidate set, kept for the whole
        // simulation. The true value is never read here, so two roots with the
        // same public history but different hidden bases produce the same belief.
        for (int i=0; i<result->bc.monsters.monsterCount && i<int(public_base.size()); ++i) {
            if (!public_base[i].applicable) continue;
            const int low=public_base[i].low, high=public_base[i].high;
            const int drawn = (high<=low) ? low
                            : low + int(rng() % static_cast<std::uint64_t>(high-low+1));
            result->bc.monsters.arr[i].miscInfo = drawn;
        }
        return result;
    }
};
PYBIND11_MODULE(_lightspeed,m) {
    py::class_<PilotBattle>(m,"PilotBattle")
        .def(py::init<const py::dict&,std::uint64_t>())
        .def("observe",&PilotBattle::observe)
        .def("step",&PilotBattle::step)
        .def("sample",&PilotBattle::sample)
        .def("debug_internals",&PilotBattle::debug_internals)
        .def("debug_set_attack_base",&PilotBattle::debug_set_attack_base)
        .def("debug_sample_with_true_base",&PilotBattle::debug_sample_with_true_base);
    m.def("build_info",[](){py::dict d; d["revision"]=STSAI_ENGINE_REVISION;
        // Local rule patches applied on top of `revision`; empty means the tree
        // is byte-for-byte upstream. Tests assert against these hashes.
        const std::string patches=STSAI_ENGINE_PATCHES;
        d["patches"]=split_csv(patches);
        d["backend"]="lightspeed_pilot"; d["belief_model"]="independent_rng_approximation";
        d["game_differential_verified"]=false; return d;});
}
