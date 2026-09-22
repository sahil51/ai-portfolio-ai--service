from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import (
    HeroInfo, Experience, Project, AutomationWorkflow, WorkflowImage,
    Education, SkillCategory, BlogPost, ContactMethod
)


async def load_all_documents(session: AsyncSession) -> list[dict]:
    docs = []

    # Hero / Profile
    hero_result = await session.execute(select(HeroInfo).limit(1))
    hero = hero_result.scalar_one_or_none()
    if hero:
        parts = []
        if hero.about_me:
            parts.append(hero.about_me)
        if hero.short_intro:
            parts.append(hero.short_intro)
        if hero.role:
            parts.append(f"Role: {hero.role}")
        if hero.tech_stack:
            parts.append(f"Tech stack: {hero.tech_stack}")
        if hero.ai_expertise:
            parts.append(f"AI expertise: {hero.ai_expertise}")
        if hero.current_company:
            parts.append(f"Current company: {hero.current_company}")
        if hero.location:
            parts.append(f"Location: {hero.location}")
        if hero.open_to_work is not None:
            parts.append(f"Open to work: {'Yes' if hero.open_to_work else 'No'}")
        parts.append(f"Email: {hero.email}")
        parts.append(f"Phone: {hero.phone}")
        parts.append(f"LinkedIn: {hero.linkedin_url}")
        parts.append(f"GitHub: {hero.github_url}")

        if hero.resume:
            r_str = str(hero.resume).strip()
            if r_str:
                resume_url = r_str if (r_str.startswith('/') or r_str.startswith('http')) else f"/media/{r_str}"
                parts.append(f"Resume PDF Direct Download Link: {resume_url}")

        docs.append({
            "id": "hero",
            "type": "profile",
            "title": f"About {hero.name}",
            "content": "\n".join(parts),
            "keywords": f"{hero.name} profile about intro role stack resume cv download pdf link",
            "source": "hero_info",
        })

        if hero.contact_description:
            docs.append({
                "id": "contact_intro",
                "type": "contact",
                "title": "Contact Introduction",
                "content": hero.contact_description,
                "keywords": "contact reach out hire collaborate",
                "source": "hero_info",
            })

    # Contact methods
    cm_result = await session.execute(select(ContactMethod).order_by(ContactMethod.order))
    contact_methods = cm_result.scalars().all()
    if contact_methods:
        cm_text = "\n".join([f"{cm.name}: {cm.value} ({cm.link})" for cm in contact_methods])
        docs.append({
            "id": "contact_methods",
            "type": "contact",
            "title": "Contact Methods",
            "content": cm_text,
            "keywords": "contact email phone whatsapp linkedin github",
            "source": "contact_method",
        })

    # Experiences
    exp_result = await session.execute(select(Experience).order_by(Experience.start_date.desc()))
    experiences = exp_result.scalars().all()
    for exp in experiences:
        parts = [
            f"{exp.role} at {exp.company}",
            f"Location: {exp.location}",
            f"Period: {exp.start_date} - {exp.end_date}",
            f"Intro: {exp.intro}",
        ]
        if exp.key_contributions:
            parts.append("Key contributions:")
            parts.extend(f"- {c}" for c in exp.get_key_contributions_list())
        if exp.company_projects:
            parts.append("Company projects:")
            parts.extend(f"- {p}" for p in exp.get_company_projects_list())
        if exp.technologies:
            parts.append(f"Technologies: {exp.technologies}")

        docs.append({
            "id": f"exp_{exp.id}",
            "type": "experience",
            "title": f"{exp.role} at {exp.company}",
            "content": "\n".join(parts),
            "keywords": f"{exp.company} {exp.role} experience work {exp.technologies}",
            "source": "experience",
        })

    # Projects
    proj_result = await session.execute(select(Project).order_by(Project.number))
    projects = proj_result.scalars().all()
    for proj in projects:
        parts = [
            f"Project {proj.number}: {proj.title}",
            f"Description: {proj.description}",
        ]
        if proj.technologies:
            parts.append(f"Technologies: {proj.technologies}")
        if proj.link:
            parts.append(f"Link: {proj.link}")
        if proj.blog_post:
            parts.append(f"In-depth Technical Case Study / Blog Article: '{proj.blog_post.title}' (URL: /blog/{proj.blog_post.slug}/)")

        docs.append({
            "id": f"proj_{proj.id}",
            "type": "project",
            "title": proj.title,
            "content": "\n".join(parts),
            "keywords": f"{proj.title} project {proj.technologies} case study detailed blog breakdown",
            "source": "project",
        })

    # Automation & n8n Workflows
    wf_result = await session.execute(
        select(AutomationWorkflow).order_by(AutomationWorkflow.order, AutomationWorkflow.id)
    )
    workflows = wf_result.scalars().all()
    for wf in workflows:
        parts = [
            f"Automation Workflow: {wf.title}",
            f"Category: {wf.category}",
            f"Description: {wf.description}",
        ]
        if wf.technologies:
            parts.append(f"Technologies / Tools: {wf.technologies}")
        if wf.link:
            parts.append(f"Workflow Link / Demo: {wf.link}")
        if wf.images:
            img_captions = [img.caption for img in wf.images if img.caption]
            if img_captions:
                parts.append(f"Key Workflow Steps: {'; '.join(img_captions)}")

        docs.append({
            "id": f"workflow_{wf.id}",
            "type": "workflow",
            "title": f"Automation Workflow: {wf.title}",
            "content": "\n".join(parts),
            "keywords": f"{wf.title} {wf.category} {wf.technologies} n8n automation workflow automated lead webhook ai agent",
            "source": "automation_workflow",
        })

    # Education
    edu_result = await session.execute(select(Education))
    educations = edu_result.scalars().all()
    for edu in educations:
        parts = [
            f"{edu.degree} at {edu.institution}",
            f"Duration: {edu.duration}",
            f"Location: {edu.location}",
        ]
        if edu.scores:
            parts.append("Scores / details:")
            parts.extend(f"- {s}" for s in edu.get_scores_list())

        docs.append({
            "id": f"edu_{edu.id}",
            "type": "education",
            "title": f"{edu.degree} - {edu.institution}",
            "content": "\n".join(parts),
            "keywords": f"{edu.institution} {edu.degree} education study",
            "source": "education",
        })

    # Skills
    cat_result = await session.execute(
        select(SkillCategory).order_by(SkillCategory.id)
    )
    categories = cat_result.scalars().all()
    for cat in categories:
        skill_names = [s.name for s in cat.skills] if cat.skills else []
        if skill_names:
            docs.append({
                "id": f"skill_cat_{cat.id}",
                "type": "skill",
                "title": f"Skills: {cat.name}",
                "content": f"Category: {cat.name}\nSkills: {', '.join(skill_names)}",
                "keywords": f"{cat.name} {' '.join(skill_names)} skills",
                "source": "skill_category",
            })

    # Blog posts (In-depth Technical Case Studies & Project Deep Dives)
    blog_result = await session.execute(
        select(BlogPost).where(BlogPost.status == 'Published').order_by(BlogPost.created_at.desc())
    )
    blogs = blog_result.scalars().all()
    import html, re
    for blog in blogs:
        raw_text = re.sub(r'<[^>]+>', ' ', blog.content or '')
        clean_content = html.unescape(' '.join(raw_text.split()))
        content_full = clean_content[:3000] if len(clean_content) > 3000 else clean_content
        summary_clean = html.unescape(' '.join(re.sub(r'<[^>]+>', ' ', blog.summary or '').split()))

        docs.append({
            "id": f"blog_{blog.id}",
            "type": "blog",
            "title": blog.title,
            "content": f"Article Title: {blog.title}\nArticle URL: /blog/{blog.slug}/\nSummary: {summary_clean}\nDetailed Article Content & Explanation:\n{content_full}",
            "keywords": f"{blog.title} {summary_clean} blog article case study technical deep dive project detail",
            "source": "blog_post",
        })

    return docs
