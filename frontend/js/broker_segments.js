// ── BrokerSegments — segment taxonomy for the national_locations retail layer ─
// Two exports:
//   SEGMENTS      — ordered list of { id, label, top, icon }
//   LEAF_TO_SEGMENT — Map<category_primary leaf string, segment id>
//   segmentForLeaf(category_primary, category_top)
//       Returns the segment id, or a synthetic "other_<category_top>" catch-all
//       so every location remains visible under its parent group even when its
//       leaf isn't explicitly mapped.  The catch-all is MANDATORY — no location
//       may vanish from the map because its leaf is unmapped.

const BrokerSegments = (() => {

  const SEGMENTS = [
    // Food & Drink
    { id: 'qsr',         label: 'QSR & Fast Food',         top: 'food_and_drink',            icon: '🍔' },
    { id: 'coffee',      label: 'Coffee & Cafe',           top: 'food_and_drink',            icon: '☕' },
    { id: 'restaurant',  label: 'Full-Service Restaurant', top: 'food_and_drink',            icon: '🍽️' },
    { id: 'bar',         label: 'Bar & Nightlife',         top: 'food_and_drink',            icon: '🍺' },
    // Shopping
    { id: 'grocery',     label: 'Grocery & Supermarket',   top: 'shopping',                  icon: '🛒' },
    { id: 'pharmacy',    label: 'Pharmacy & Drugstore',    top: 'shopping',                  icon: '💊' },
    { id: 'dollar',      label: 'Dollar & Discount',       top: 'shopping',                  icon: '🏷️' },
    { id: 'apparel',     label: 'Apparel & Clothing',      top: 'shopping',                  icon: '👕' },
    { id: 'home_imp',    label: 'Home Improvement',        top: 'shopping',                  icon: '🔨' },
    { id: 'mobile_elec', label: 'Mobile & Electronics',    top: 'shopping',                  icon: '📱' },
    // Services & Business
    { id: 'bank',        label: 'Bank & Financial',        top: 'services_and_business',     icon: '🏦' },
    // Lifestyle Services
    { id: 'beauty',      label: 'Beauty & Personal Care',  top: 'lifestyle_services',        icon: '💈' },
    { id: 'fitness',     label: 'Fitness & Wellness',      top: 'lifestyle_services',        icon: '🏋️' },
    // Travel & Transportation
    { id: 'auto_svc',    label: 'Auto Service',            top: 'travel_and_transportation', icon: '🔧' },
    { id: 'gas',         label: 'Gas & Fuel',              top: 'travel_and_transportation', icon: '⛽' },
  ];

  // Leaf → segment id.  Keys are EXACT category_primary values from the DB.
  // Anything NOT listed here falls through to the catch-all "other_<top>"
  // via segmentForLeaf() — do not delete leaves to "clean up" the map.
  const LEAF_TO_SEGMENT = {
    // QSR & Fast Food
    fast_food_restaurant: 'qsr',
    burger_restaurant: 'qsr',
    sandwich_shop: 'qsr',
    chicken_restaurant: 'qsr',
    chicken_wings_restaurant: 'qsr',
    taco_restaurant: 'qsr',
    hot_dog_restaurant: 'qsr',
    pizza_restaurant: 'qsr',
    cheesesteak_restaurant: 'qsr',

    // Coffee & Cafe
    coffee_shop: 'coffee',
    cafe: 'coffee',
    tea_room: 'coffee',
    donuts: 'coffee',
    bagel_shop: 'coffee',
    coffee_roastery: 'coffee',
    smoothie_juice_bar: 'coffee',
    bubble_tea: 'coffee',

    // Full-Service Restaurant
    restaurant: 'restaurant',
    american_restaurant: 'restaurant',
    italian_restaurant: 'restaurant',
    mexican_restaurant: 'restaurant',
    chinese_restaurant: 'restaurant',
    bar_and_grill_restaurant: 'restaurant',
    seafood_restaurant: 'restaurant',
    steakhouse: 'restaurant',
    breakfast_and_brunch_restaurant: 'restaurant',
    diner: 'restaurant',
    thai_restaurant: 'restaurant',
    sushi_restaurant: 'restaurant',
    indian_restaurant: 'restaurant',
    mediterranean_restaurant: 'restaurant',
    asian_restaurant: 'restaurant',
    japanese_restaurant: 'restaurant',
    greek_restaurant: 'restaurant',
    korean_restaurant: 'restaurant',
    vietnamese_restaurant: 'restaurant',
    barbecue_restaurant: 'restaurant',
    buffet_restaurant: 'restaurant',

    // Bar & Nightlife
    bar: 'bar',
    pub: 'bar',
    brewery: 'bar',
    sports_bar: 'bar',
    cocktail_bar: 'bar',
    lounge: 'bar',
    wine_bar: 'bar',
    gastropub: 'bar',
    hookah_bar: 'bar',
    beer_bar: 'bar',
    dive_bar: 'bar',
    irish_pub: 'bar',
    distillery: 'bar',
    winery: 'bar',
    brewpub: 'bar',
    cigar_bar: 'bar',

    // Grocery & Supermarket
    grocery_store: 'grocery',
    supermarket: 'grocery',
    specialty_grocery_store: 'grocery',
    organic_grocery_store: 'grocery',
    international_grocery_store: 'grocery',
    asian_grocery_store: 'grocery',
    health_food_store: 'grocery',
    farmers_market: 'grocery',
    butcher_shop: 'grocery',
    fishmonger: 'grocery',

    // Pharmacy & Drugstore
    pharmacy: 'pharmacy',
    drugstore: 'pharmacy',

    // Dollar & Discount
    discount_store: 'dollar',
    thrift_store: 'dollar',
    wholesale_store: 'dollar',
    outlet_store: 'dollar',
    pawn_shop: 'dollar',
    flea_market: 'dollar',

    // Apparel & Clothing
    clothing_store: 'apparel',
    womens_clothing_store: 'apparel',
    mens_clothing_store: 'apparel',
    childrens_clothing_store: 'apparel',
    shoe_store: 'apparel',
    boutique: 'apparel',
    fashion_accessories_store: 'apparel',
    lingerie_store: 'apparel',
    bridal_shop: 'apparel',
    designer_clothing: 'apparel',
    sports_wear: 'apparel',

    // Home Improvement
    hardware_store: 'home_imp',
    home_improvement_store: 'home_imp',
    building_supply_store: 'home_imp',
    paint_store: 'home_imp',
    flooring_store: 'home_imp',
    lumber_store: 'home_imp',
    lighting_store: 'home_imp',
    kitchen_and_bath: 'home_imp',
    tile_store: 'home_imp',

    // Mobile & Electronics
    mobile_phone_store: 'mobile_elec',
    electronics: 'mobile_elec',
    computer_store: 'mobile_elec',
    mobile_phone_accessories: 'mobile_elec',
    video_game_store: 'mobile_elec',
    audio_visual_equipment_store: 'mobile_elec',

    // Bank & Financial  (services_and_business)
    bank_credit_union: 'bank',
    banks: 'bank',
    credit_union: 'bank',
    atms: 'bank',
    financial_service: 'bank',
    financial_advising: 'bank',
    mortgage_broker: 'bank',
    mortgage_lender: 'bank',
    check_cashing_payday_loans: 'bank',
    money_transfer_services: 'bank',
    tax_services: 'bank',
    insurance_agency: 'bank',
    installment_loans: 'bank',

    // Beauty & Personal Care  (lifestyle_services)
    beauty_salon: 'beauty',
    hair_salon: 'beauty',
    nail_salon: 'beauty',
    barber: 'beauty',
    spas: 'beauty',
    day_spa: 'beauty',
    medical_spa: 'beauty',
    tanning_salon: 'beauty',
    waxing: 'beauty',
    massage: 'beauty',
    massage_therapy: 'beauty',
    skin_care: 'beauty',
    makeup_artist: 'beauty',
    kids_hair_salon: 'beauty',
    hair_stylist: 'beauty',

    // Fitness & Wellness  (lifestyle_services)
    health_and_wellness_club: 'fitness',
    health_spa: 'fitness',
    weight_loss_center: 'fitness',
    meditation_center: 'fitness',
    wellness_program: 'fitness',

    // Auto Service  (travel_and_transportation)
    automotive_repair: 'auto_svc',
    auto_body_shop: 'auto_svc',
    tire_dealer_and_repair: 'auto_svc',
    tire_shop: 'auto_svc',
    oil_change_station: 'auto_svc',
    car_wash: 'auto_svc',
    auto_detailing: 'auto_svc',
    brake_service_and_repair: 'auto_svc',
    transmission_repair: 'auto_svc',
    auto_glass_service: 'auto_svc',
    towing_service: 'auto_svc',
    automotive_services_and_repair: 'auto_svc',

    // Gas & Fuel  (travel_and_transportation)
    gas_station: 'gas',
    truck_gas_station: 'gas',
    ev_charging_station: 'gas',
  };

  // Labels for the 5 Overture top-level categories in the panel header
  const TOP_LABELS = {
    food_and_drink:            { label: 'Food & Drink',              icon: '🍽️' },
    shopping:                  { label: 'Shopping',                  icon: '🛍️' },
    services_and_business:     { label: 'Services & Business',       icon: '🏢'  },
    lifestyle_services:        { label: 'Lifestyle Services',        icon: '💈'  },
    travel_and_transportation: { label: 'Travel & Transportation',   icon: '✈️' },
  };

  /**
   * Returns the segment id for a given (category_primary, category_top) pair.
   * Falls back to "other_<category_top>" for unmapped leaves — this catch-all
   * is mandatory so every location stays visible under its parent group.
   * Example: segmentForLeaf('veterinarian', 'lifestyle_services')
   *          → 'other_lifestyle_services'   (shown as "Other Lifestyle Services")
   */
  function segmentForLeaf(category_primary, category_top) {
    if (category_primary && LEAF_TO_SEGMENT[category_primary]) {
      return LEAF_TO_SEGMENT[category_primary];
    }
    return category_top ? `other_${category_top}` : 'other_unknown';
  }

  return { SEGMENTS, LEAF_TO_SEGMENT, TOP_LABELS, segmentForLeaf };
})();
