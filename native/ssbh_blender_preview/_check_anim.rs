fn main() {
    let path = r#"C:\Users\Cesar\Documents\Games\Citron\user\sdmc\ultimate\mods\(Moveset) Vegito\fighter\captain\motion\body\c80\a00transformssjb.nuanmb"#;
    let anim = ssbh_data::anim_data::AnimData::from_file(path).unwrap();
    for g in &anim.groups {
        println!("group {:?}", g.group_type);
        for n in &g.nodes {
            println!(" node {}", n.name);
            for t in &n.tracks {
                match &t.values {
                    ssbh_data::anim_data::TrackValues::Vector4(v) => println!("  {} Vector4 {:?}", t.name, v.first()),
                    ssbh_data::anim_data::TrackValues::UvTransform(v) => println!("  {} UvTransform {:?}", t.name, v.first()),
                    other => println!("  {} other {:?}", t.name, std::mem::discriminant(other)),
                }
            }
        }
    }
}
